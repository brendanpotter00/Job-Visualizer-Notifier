"""Launch Radar loop CLI (CONTRACT §6.2).

Run from the repo root as ``python -m scripts.launch_radar.radar`` (the
``radar.sh`` launcher does this with the right dependencies and env file):

  monitors-ensure                     create any missing active Monitor ($0.01 each, reserved first)
  run [--max-companies N] [--budget USD] [--exclude d1,d2] [--deadline-s S] [--dry-run]
  backfill [--days 30] [--limit 20] [--generator base] [--exclude d1,d2] [--deadline-s S] [--dry-run] [--new]
                                      one FindAll sweep of the past --days days into the queue
                                      (base: $0.25 + $0.03/match, then $0.01/match enrichment and
                                      $0.005/domain lookup, each reserved first)
  monitors-cancel                     cancel every active Monitor and confirm it (free)
  heartbeat --status ok|error [--note TEXT]   append one line to $STATE_DIR/heartbeat.log
  import --file PATH [--dry-run]      post cards exported by export_cards.py to BACKEND_URL
                                      (no Parallel calls, nothing reserved; a 409 duplicate is skipped)
  refresh (--domains d1,d2 | --missing-talent) [--include-archived] [--budget USD] [--deadline-s S] [--dry-run]
                                      re-research cards with no leaders: a new brief (with founders,
                                      $0.025) + the founders' pedigree ($0.01 each), reserved first;
                                      then PUT the rescored payload (status and posted_at stay).
                                      Archived cards are skipped unless --include-archived
  rescore (--domains d1,d2 | --all) [--dry-run]
                                      recompute the scores of existing cards from what they store
                                      (free: no Parallel calls, no run, nothing reserved); PUT only
                                      the cards whose scores changed. Every live status is selected

Exit codes: 0 done · 1 error · 2 stopped on the budget · 3 incomplete (re-run to resume).

Secrets: the Parallel SDK reads PARALLEL_API_KEY itself; this program only
checks that it and INTERNAL_API_KEY are set and never prints either.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path
from types import FrameType
from typing import Callable, Sequence

from .backend_client import BackendClient, BackendError
from .backfill import GENERATORS, BackfillOptions, backfill
from .config import ConfigError, load_config, state_dir_from
from .domains import normalize_domain
from .importer import ImportFileError, import_cards, load_export
from .leaders import abort_all_deadlines
from .monitors import MonitorCancelError
from .parallel_client import make_client
from .pipeline import (
    EXIT_ERROR,
    EXIT_OK,
    Deps,
    RunOptions,
    monitors_cancel,
    monitors_ensure,
    run,
)
from .refresh import RefreshOptions, refresh
from .rescore import RescoreOptions, rescore
from .state import StateStore, iso, utc_now

MAX_RUN_BUDGET = 5.0


def log(msg: str) -> None:
    print(f"[radar] {iso(utc_now())} {msg}", flush=True)


def _budget(value: str) -> float:
    v = float(value)
    if not 0 < v <= MAX_RUN_BUDGET:
        raise argparse.ArgumentTypeError(f"--budget must be > 0 and <= {MAX_RUN_BUDGET}")
    return v


def _non_negative_int(value: str) -> int:
    v = int(value)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


def _int_between(lo: int, hi: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        v = int(value)
        if not lo <= v <= hi:
            raise argparse.ArgumentTypeError(f"must be {lo}..{hi}")
        return v

    return parse


def _domain_list(flag: str) -> Callable[[str], frozenset[str]]:
    def parse(value: str) -> frozenset[str]:
        out = set()
        for raw in value.split(","):
            if raw.strip():
                dom = normalize_domain(raw)
                if not dom:
                    raise argparse.ArgumentTypeError(f"{flag}: {raw.strip()!r} is not a domain")
                out.add(dom)
        return frozenset(out)

    return parse


_exclude = _domain_list("--exclude")


def _on_sigterm(signum: int, frame: FrameType | None) -> None:
    """The skill's Bash timeout or the wrapper's watchdog sends SIGTERM. Stop the workers
    (their deadlines expire, state is saved) and unwind so ``run()`` finishes the backend
    run as "error" instead of leaving it "running" forever."""
    abort_all_deadlines()
    raise SystemExit(128 + signum)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="radar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("monitors-ensure", help="create any missing active Monitor")
    r = sub.add_parser("run", help="one loop invocation")
    r.add_argument("--max-companies", type=_non_negative_int, default=3,
                   help="new companies to start (resumed ones always continue)")
    r.add_argument("--budget", type=_budget, default=1.00, help="this run's spend cap in USD")
    r.add_argument("--exclude", type=_exclude, default=frozenset(), help="comma-separated domains to skip")
    r.add_argument("--deadline-s", type=float, default=540.0, help="stop and save state after this many seconds")
    r.add_argument("--dry-run", action="store_true", help="read events and /seen only; spend and write nothing")
    bf = sub.add_parser("backfill", help="one FindAll sweep of the past --days days into the queue")
    bf.add_argument("--days", type=_int_between(1, 90), default=30, help="window: the last N days (UTC)")
    bf.add_argument("--limit", type=_int_between(5, 100), default=20, help="FindAll match_limit")
    bf.add_argument("--generator", choices=GENERATORS, default="base", help="FindAll generator")
    bf.add_argument("--exclude", type=_exclude, default=frozenset(), help="comma-separated domains to skip")
    bf.add_argument("--deadline-s", type=float, default=540.0,
                    help="stop polling and save state after this many seconds (re-run to resume)")
    bf.add_argument("--dry-run", action="store_true", help="print the requests and the estimate; call nothing")
    bf.add_argument("--new", action="store_true", help="start a new (paid) sweep after a finished one")
    sub.add_parser("monitors-cancel", help="cancel every active Monitor and confirm")
    hb =sub.add_parser("heartbeat", help="append the run's final heartbeat line")
    hb.add_argument("--status", choices=["ok", "error"], required=True)
    hb.add_argument("--note")
    im = sub.add_parser("import", help="post cards exported by export_cards.py (no Parallel calls)")
    im.add_argument("--file", type=Path, required=True, help="a launch-radar-cards/v1 JSON export")
    im.add_argument("--dry-run", action="store_true",
                    help="validate the file and ask GET /seen which cards exist; post nothing")
    rf = sub.add_parser("refresh", help="re-research cards with no leaders (new brief with founders + pedigree)")
    which = rf.add_mutually_exclusive_group(required=True)
    which.add_argument("--domains", type=_domain_list("--domains"), help="comma-separated card domains")
    which.add_argument("--missing-talent", action="store_true",
                       help="every new or saved card with no leaders' part of Talent (no leader data)")
    rf.add_argument("--include-archived", action="store_true",
                    help="also refresh archived cards (skipped by default: they were set aside)")
    rf.add_argument("--budget", type=_budget, default=1.00, help="this run's spend cap in USD")
    rf.add_argument("--deadline-s", type=float, default=540.0, help="stop and save state after this many seconds")
    rf.add_argument("--dry-run", action="store_true", help="list the cards and the estimate; call nothing billed")
    rs = sub.add_parser("rescore", help="recompute stored cards' scores (free, no Parallel calls)")
    which = rs.add_mutually_exclusive_group(required=True)
    which.add_argument("--domains", type=_domain_list("--domains"), help="comma-separated card domains")
    which.add_argument("--all", dest="all_cards", action="store_true", help="every live card (new, saved, archived)")
    rs.add_argument("--dry-run", action="store_true", help="print the old and new scores; write nothing")
    return p


def main(argv: Sequence[str] | None = None, *, deps: Deps | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "heartbeat":
        line = StateStore(state_dir_from(os.environ)).heartbeat(args.status, args.note)
        print(line)
        return EXIT_OK
    if args.cmd == "import":  # validate the whole file before any config or backend call
        try:
            export = load_export(args.file)
        except ImportFileError as e:
            print(f"import: {e}", file=sys.stderr)
            return EXIT_ERROR

    if deps is None:
        billed = args.cmd in ("monitors-ensure", "monitors-cancel", "run") or (
            args.cmd in ("backfill", "refresh") and not args.dry_run)
        try:
            cfg = load_config(need_parallel=billed)
        except ConfigError as e:
            print(f"config: {e.message()}", file=sys.stderr)
            return EXIT_ERROR
        log(f"backend {cfg.backend_url} · internal key {'set' if cfg.internal_api_key else 'not set'}")
        deps = Deps(backend=BackendClient(cfg.backend_url, cfg.internal_api_key), make_client=make_client,
                    store=StateStore(cfg.state_dir), log=log)
        signal.signal(signal.SIGTERM, _on_sigterm)  # CLI only; tests inject deps and keep pytest's handlers

    try:
        if args.cmd == "monitors-ensure":
            return monitors_ensure(deps)
        if args.cmd == "monitors-cancel":
            return monitors_cancel(deps)
        if args.cmd == "run":
            opts = RunOptions(max_companies=args.max_companies, budget=args.budget, exclude=args.exclude,
                              deadline_s=args.deadline_s, dry_run=args.dry_run)
            return run(opts, deps)
        if args.cmd == "backfill":
            return backfill(BackfillOptions(days=args.days, limit=args.limit, generator=args.generator,
                                            exclude=args.exclude, deadline_s=args.deadline_s,
                                            dry_run=args.dry_run, new=args.new), deps)
        if args.cmd == "import":
            return import_cards(export, deps, dry_run=args.dry_run)
        if args.cmd == "refresh":
            return refresh(RefreshOptions(domains=args.domains or frozenset(), missing_talent=args.missing_talent,
                                          include_archived=args.include_archived, budget=args.budget,
                                          deadline_s=args.deadline_s, dry_run=args.dry_run), deps)
        if args.cmd == "rescore":
            return rescore(RescoreOptions(domains=args.domains or frozenset(), all_cards=args.all_cards,
                                          dry_run=args.dry_run), deps)
    except (BackendError, MonitorCancelError) as e:
        log(f"error: {e}")
        return EXIT_ERROR
    finally:
        deps.backend.close()
    raise AssertionError(f"unhandled command {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
