"""On-demand golden-set eval for Tier-2 location normalization (Claude Haiku).

Runs the curated + prod-sampled golden set against the REAL model
(``normalize_location_via_llm``) and scores structured fields. Human-run, never
CI — it costs real Anthropic spend and the model is nondeterministic.

Canonical invocation (from the repo ROOT, so .env.local is auto-loaded):

    PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all

See ``README.md`` for the full how/when. Exit codes:
    0  gating accuracy >= --threshold AND no --baseline regressions
    1  below threshold OR a case that passed in the baseline now fails
    2  setup error (ANTHROPIC_API_KEY not set)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import anthropic
from anthropic import AsyncAnthropic

from ..config import settings
from ..services.llm_client import (
    LocationLLMError,
    MissingAnthropicKeyError,
    build_message_params,
    extract_text_content,
    normalize_location_via_llm,
    parse_locations_text,
)
from .golden_set import CURATED_CASES
from .scoring import find_regressions, normalize_fields, score_case, summarize

_HERE = os.path.dirname(os.path.abspath(__file__))
# Every run drops a timestamped JSON here (gitignored). The committed reference for
# regression diffs is eval-baseline.json in the package root, NOT this dir.
_RESULTS_DIR = os.path.join(_HERE, "results")

# Rough only — for a "this costs about X" line, not billing. Update if Haiku
# pricing or the prompt size changes materially.
_EST_COST_PER_CALL_USD = 0.0015


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_results_file(report: dict) -> str:
    """Persist one run's full report to results/eval-<ts>-<set>[-batch].json."""
    os.makedirs(_RESULTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "-batch" if report.get("mode") == "batch" else ""
    path = os.path.join(_RESULTS_DIR, f"eval-{stamp}-{report['set']}{suffix}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    return path


def _load_prod_cases() -> list[dict]:
    with open(os.path.join(_HERE, "prod_sample.json")) as f:
        data = json.load(f)
    return data["cases"] if isinstance(data, dict) else data


def _select_cases(which: str) -> list[dict]:
    if which == "curated":
        return list(CURATED_CASES)
    if which == "prod":
        return _load_prod_cases()
    return list(CURATED_CASES) + _load_prod_cases()


def _loc_to_dict(loc) -> dict:
    return {
        "canonical_name": loc.canonical_name, "kind": loc.kind, "city": loc.city,
        "region": loc.region, "country": loc.country,
        "remote_scope": loc.remote_scope, "confidence": loc.confidence,
    }


# Transient — worth a retry (prod's real retry path is Procrastinate, absent here).
_RETRYABLE = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


async def _call_with_retry(raw: str, retries: int = 2):
    """Return (produced_locations, error_str). Retries only transient API errors;
    permanent 4xx (auth, billing, bad-request) fail fast — retrying them is waste."""
    delay = 0.5
    for attempt in range(retries + 1):
        try:
            return await normalize_location_via_llm(raw), None
        except MissingAnthropicKeyError:
            raise  # aborts the whole run (caught in main)
        except _RETRYABLE as exc:
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return None, f"APIError: {type(exc).__name__}: {exc}"
        except anthropic.APIError as exc:
            return None, f"APIError: {type(exc).__name__}: {exc}"  # permanent — no retry
        except LocationLLMError as exc:
            return None, f"LocationLLMError: {exc}"


# An "outcome" is one model result for one raw string: (produced|None, error|None).
# We resolve each DISTINCT raw string `repeat` times and reuse the outcomes for
# every case that shares that string — mirroring production's by-string alias cache
# (110 cases collapse to ~94 distinct strings), so we never pay for a dup.

async def _resolve_one_sync(raw: str, sem: asyncio.Semaphore):
    async with sem:
        produced, error = await _call_with_retry(raw)
    if produced is not None:
        produced = [_loc_to_dict(loc) for loc in produced]
    return produced, error


async def _resolve_sync(distinct: list[str], repeat: int, sem: asyncio.Semaphore) -> dict:
    """{raw: [outcome] * repeat} via concurrent sync calls (the production path)."""
    order = [(raw, rep) for raw in distinct for rep in range(repeat)]
    flat = await asyncio.gather(*(_resolve_one_sync(raw, sem) for raw, _ in order))
    outcomes: dict[str, list] = defaultdict(list)
    for (raw, _), outcome in zip(order, flat):
        outcomes[raw].append(outcome)
    return outcomes


async def _resolve_batch(distinct: list[str], repeat: int, poll_interval: float) -> dict:
    """{raw: [outcome] * repeat} via the Anthropic Message Batches API (50% cost).

    Uses the SAME ``build_message_params`` (incl. the structured-outputs schema) and
    ``parse_locations_text`` as production — only the transport differs. Async:
    submit one batch, poll until ended, map results back by custom_id.
    """
    client = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=60.0)
    order: list[tuple[str, str]] = []  # (custom_id, raw)
    requests = []
    for raw in distinct:
        for _ in range(repeat):
            cid = f"c{len(requests)}"
            order.append((cid, raw))
            requests.append({"custom_id": cid, "params": build_message_params(raw)})

    batch = await client.messages.batches.create(requests=requests)
    print(f"submitted batch {batch.id} ({len(requests)} requests); polling...", flush=True)
    waited = 0.0
    while True:
        status = (await client.messages.batches.retrieve(batch.id)).processing_status
        if status == "ended":
            break
        if waited >= 1800:
            raise RuntimeError(f"batch {batch.id} not done after {waited:.0f}s (status={status})")
        await asyncio.sleep(poll_interval)
        waited += poll_interval

    by_cid: dict[str, tuple] = {}
    async for entry in await client.messages.batches.results(batch.id):
        res = entry.result
        if res.type == "succeeded":
            try:
                locs = parse_locations_text(extract_text_content(res.message))
                by_cid[entry.custom_id] = ([_loc_to_dict(loc) for loc in locs], None)
            except LocationLLMError as exc:
                by_cid[entry.custom_id] = (None, f"LocationLLMError: {exc}")
        else:
            detail = getattr(res, "error", res.type)
            by_cid[entry.custom_id] = (None, f"APIError: batch {res.type}: {detail}")

    outcomes: dict[str, list] = defaultdict(list)
    for cid, raw in order:
        outcomes[raw].append(by_cid.get(cid, (None, "APIError: missing batch result")))
    return outcomes


def _score_case_from_outcomes(case: dict, outcomes: list, repeat: int) -> dict:
    runs = [score_case(case, produced, error) for produced, error in outcomes]
    final = dict(runs[0])
    if repeat > 1:
        passes = sum(1 for r in runs if r["passed"])
        final["passed"] = passes > repeat / 2
        final["verdict"] = "pass" if final["passed"] else "fail"
        final["flaky"] = len({r["passed"] for r in runs}) > 1
        final["runs_passed"] = f"{passes}/{repeat}"
    final["expect_below_floor"] = case.get("expect_below_floor", False)
    return final


def _fmt_locs(locs) -> str:
    if not locs:
        return "[]"
    return " | ".join(
        "(" + ",".join("-" if x is None else str(x) for x in normalize_fields(loc)) + ")"
        for loc in locs
    )


def _print_report(results, summary, elapsed, args, regressions, total_calls) -> None:
    failures = [r for r in results if r["gating"] and not r["passed"]]
    shown = results if args.verbose else failures
    header = "ALL CASES" if args.verbose else "GATING FAILURES"
    print(f"\n===== {header} ({len(shown)}) =====")
    for r in shown:
        flag = "PASS" if r["passed"] else r["verdict"].upper()
        gate = "" if r["gating"] else " [info]"
        flaky = " FLAKY" if r.get("flaky") else ""
        mc = r.get("max_confidence")
        conf = f" conf={mc:.2f}" if mc is not None else ""
        print(f"\n  [{flag}{gate}{flaky}] {r['id']}  ({r['category']}){conf}")
        print(f"      raw:      {r['raw']!r}")
        print(f"      expected: {_fmt_locs(r['expected'])}")
        if r.get("error"):
            print(f"      ERROR:    {r['error']}")
        else:
            print(f"      produced: {_fmt_locs(r['produced'])}")
        if r.get("primary_match") is False:
            print("      ! primary mismatch (produced[0] != expected[0])")

    # low-confidence-by-design expectations
    lc = [r for r in results if r.get("expect_below_floor")]
    lc_held = sum(1 for r in lc if r.get("below_floor"))

    acc = summary["gating_accuracy"]
    acc_s = "n/a" if acc is None else f"{acc * 100:.1f}%"
    print("\n===== SUMMARY =====")
    print(f"  gating accuracy:        {acc_s}  ({summary['gating_pass']}/{summary['gating_total']})  threshold={args.threshold * 100:.0f}%")
    print(f"  cases:                  {summary['total_cases']} total  "
          f"({summary['gating_total']} gating, {summary['informational_total']} informational)")
    print(f"  primary mismatches:     {summary['primary_mismatches']}")
    print(f"  below confidence floor: {summary['below_confidence_floor']}  "
          f"(low-conf-by-design held: {lc_held}/{len(lc)})")
    print(f"  LLM errors / API errors:{summary['llm_errors']} / {summary['api_errors']}")
    print("  per-category gating accuracy:")
    for cat, d in sorted(summary["by_category"].items()):
        print(f"      {cat:<16} {d['pass']}/{d['total']}")
    est = total_calls * _EST_COST_PER_CALL_USD * (0.5 if args.batch else 1.0)
    mode = "batch @50%" if args.batch else "sync"
    print(f"  LLM calls:              {total_calls} ({mode})  (~${est:.2f} rough)")
    print(f"  wall-clock:             {elapsed:.1f}s")
    if args.baseline:
        if regressions:
            print(f"\n  !! {len(regressions)} REGRESSION(S) vs baseline (passed -> now failing):")
            for cid in regressions:
                print(f"       - {cid}")
        else:
            print("\n  no regressions vs baseline.")


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Location-normalization golden-set eval (real Haiku).")
    p.add_argument("--set", choices=["curated", "prod", "all"], default="all")
    p.add_argument("--json", metavar="PATH", help="write the full structured report to JSON")
    p.add_argument("--baseline", metavar="PATH", help="compare verdicts to a saved JSON; flag regressions")
    p.add_argument("--repeat", type=int, default=1, help="run each case N times; gate on majority")
    p.add_argument("--threshold", type=float, default=0.90, help="minimum gating accuracy [0..1]")
    p.add_argument("--concurrency", type=int, default=5, help="max concurrent LLM calls (sync mode)")
    p.add_argument("--batch", action="store_true",
                   help="use the Anthropic Message Batches API (50%% cost, async). Default is the "
                        "sync path, which exercises the exact production call.")
    p.add_argument("--poll-interval", type=float, default=5.0, help="batch poll interval seconds")
    p.add_argument("--verbose", action="store_true", help="print every case, not just failures")
    return p.parse_args(argv)


async def _main_async(args) -> int:
    if not settings.anthropic_api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY is not set. Add it to .env.local at the repo "
            "root (and run from the repo root) or `export ANTHROPIC_API_KEY=...`.",
            file=sys.stderr,
        )
        return 2

    cases = _select_cases(args.set)
    distinct = list(dict.fromkeys(c["raw"] for c in cases))  # ordered unique (dedup)
    total_calls = len(distinct) * args.repeat
    print(
        f"{len(cases)} cases -> {len(distinct)} distinct strings x{args.repeat} = "
        f"{total_calls} LLM calls ({'batch' if args.batch else 'sync'} mode)",
        flush=True,
    )

    t0 = time.monotonic()
    try:
        if args.batch:
            outcomes = await _resolve_batch(distinct, args.repeat, args.poll_interval)
        else:
            sem = asyncio.Semaphore(args.concurrency)
            outcomes = await _resolve_sync(distinct, args.repeat, sem)
    except MissingAnthropicKeyError:
        print("ERROR: ANTHROPIC_API_KEY became unavailable mid-run.", file=sys.stderr)
        return 2
    elapsed = time.monotonic() - t0

    results = [_score_case_from_outcomes(c, outcomes[c["raw"]], args.repeat) for c in cases]
    summary = summarize(results)

    regressions: list[str] = []
    if args.baseline:
        with open(args.baseline) as f:
            base = json.load(f)
        base_results = base["results"] if isinstance(base, dict) else base
        regressions = find_regressions(results, base_results)

    # Systemic API failure (every call errored on access — bad/no key, billing,
    # auth, outage) is NOT a quality result; it gets exit 2, not a misleading "0%".
    systemic = bool(results) and summary["api_errors"] == len(results)
    acc = summary["gating_accuracy"]
    if systemic:
        rc = 2
    elif acc is not None and acc >= args.threshold and not regressions:
        rc = 0
    else:
        rc = 1

    # Persist EVERY run's full results to the gitignored results/ dir.
    report = {
        "timestamp": _now_iso(),
        "set": args.set,
        "mode": "batch" if args.batch else "sync",
        "repeat": args.repeat,
        "threshold": args.threshold,
        "total_calls": total_calls,
        "elapsed_s": round(elapsed, 2),
        "exit_code": rc,
        "summary": summary,
        "regressions": regressions,
        "results": results,
    }
    persisted = _write_results_file(report)
    print(f"persisted results -> {persisted}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"wrote report -> {args.json}")

    if systemic:
        sample = next((r["error"] for r in results if r.get("error")), "")
        print(
            f"\nERROR: all {len(results)} calls failed with an API error — this is "
            f"an API-access problem, not a quality result.\n  e.g. {sample}\n"
            "  (check ANTHROPIC_API_KEY validity and the account credit balance.)",
            file=sys.stderr,
        )
        return rc

    _print_report(results, summary, elapsed, args, regressions, total_calls)
    return rc


def main(argv=None) -> int:
    return asyncio.run(_main_async(_parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
