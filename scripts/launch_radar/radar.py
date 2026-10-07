"""Launch Radar loop CLI (CONTRACT §6.2).

Run from the repo root as ``python -m scripts.launch_radar.radar`` (the
``radar.sh`` launcher does this with the right dependencies and env file):

  monitors-ensure                     create any missing active Monitor ($0.01 each, reserved first)
  run [--max-companies N] [--budget USD] [--exclude d1,d2] [--deadline-s S] [--dry-run]
  monitors-cancel                     cancel every active Monitor and confirm it (free)
  pr-candidates [--limit 1]           print GET /pr-candidates as JSON
  set-pr --card-id N --pr-url URL     record the add-company PR on a card
  heartbeat --status ok|error [--note TEXT]   append one line to $STATE_DIR/heartbeat.log

Exit codes: 0 done · 1 error · 2 stopped on the budget · 3 incomplete (re-run to resume).

Secrets: the Parallel SDK reads PARALLEL_API_KEY itself; this program only
checks that it and INTERNAL_API_KEY are set and never prints either.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
from types import FrameType
from typing import Sequence

from .backend_client import BackendClient, BackendError
from .config import ConfigError, load_config, state_dir_from
from .domains import normalize_domain
from .leaders import abort_all_deadlines
from .monitors import MonitorCancelError
from .parallel_client import make_client
from .pipeline import EXIT_ERROR, EXIT_OK, Deps, RunOptions, monitors_cancel, monitors_ensure, run
from .state import StateStore, iso, utc_now

PR_URL = re.compile(r"^https://github\.com/brendanpotter00/Job-Visualizer-Notifier/pull/\d+$")
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


def _exclude(value: str) -> frozenset[str]:
    out = set()
    for raw in value.split(","):
        if raw.strip():
            dom = normalize_domain(raw)
            if not dom:
                raise argparse.ArgumentTypeError(f"--exclude: {raw.strip()!r} is not a domain")
            out.add(dom)
    return frozenset(out)


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
    sub.add_parser("monitors-cancel", help="cancel every active Monitor and confirm")
    pc = sub.add_parser("pr-candidates", help="cards ready for an add-company PR")
    pc.add_argument("--limit", type=int, default=1, choices=range(1, 6), metavar="1..5")
    sp = sub.add_parser("set-pr", help="record the add-company PR URL on a card")
    sp.add_argument("--card-id", type=int, required=True)
    sp.add_argument("--pr-url", required=True)
    hb = sub.add_parser("heartbeat", help="append the run's final heartbeat line")
    hb.add_argument("--status", choices=["ok", "error"], required=True)
    hb.add_argument("--note")
    return p


def main(argv: Sequence[str] | None = None, *, deps: Deps | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "heartbeat":
        line = StateStore(state_dir_from(os.environ)).heartbeat(args.status, args.note)
        print(line)
        return EXIT_OK
    if args.cmd == "set-pr" and not PR_URL.match(args.pr_url):
        print("set-pr: --pr-url must be a pull request URL in brendanpotter00/Job-Visualizer-Notifier", file=sys.stderr)
        return EXIT_ERROR

    if deps is None:
        billed = args.cmd in ("monitors-ensure", "monitors-cancel", "run")
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
        if args.cmd == "pr-candidates":
            print(json.dumps({"cards": deps.backend.pr_candidates(args.limit)}, indent=2))
            return EXIT_OK
        if args.cmd == "set-pr":
            print(json.dumps(deps.backend.set_pr(args.card_id, args.pr_url)))
            return EXIT_OK
    except (BackendError, MonitorCancelError) as e:
        log(f"error: {e}")
        return EXIT_ERROR
    finally:
        deps.backend.close()
    raise AssertionError(f"unhandled command {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
