"""The Tier-2 subcategory backfill: projection, matching, the run loop and the
throttled drain to JVN.

Three things live here and they are deliberately in one module:

  `chunk_rows` / `match_results_to_chunk`  (BF-6) the injection boundary and the
      replacement for positional id-repair
  `run_backfill`                           (BF-9) the night's label run
  `push_subcategories`                     (BF-12b) the morning's paced drain

⚠ THE INJECTION BOUNDARY IS STRUCTURAL HERE, NOT PROCEDURAL. `claude_code.py`'s
module docstring reserves the sandboxed sub-agent fan-out for untrusted scraped
text and limits headless `claude -p` to trusted input. A job description CANNOT
leak into a `claude -p` prompt on this lane because the row handed to the prompt
builder has nowhere to put one: `chunk_rows` emits exactly five keys and RAISES
if the source row carries a description at all.

⚠ DISCLOSURE, required in this docstring by the plan's open risk #5: the `tags`
this module ships to the model are the ENRICHER'S OWN v6 output, not company
tags. JVN's `_JOB_PROJECTION` narrows `details` to `department` +
`experience_level` and has never shipped `details->'tags'`. So the tag layer is
NOT independent evidence — it is v6 grading its own homework — and every place
that reports a tag-layer number must say so.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# The complete key set of a trusted backfill row. Exactly these five, in this
# order, and nothing else — this tuple IS the injection boundary.
CHUNK_ROW_KEYS: tuple[str, ...] = (
    "job_listing_id", "source_id", "title", "company", "tags",
)

# Keys whose presence on a source row means a description would otherwise be
# copied through. Their appearance is a programming error, not a data problem,
# so `chunk_rows` raises rather than dropping them quietly: a silent drop would
# make the boundary procedural again the next time someone widens the selector.
_FORBIDDEN_SOURCE_KEYS: tuple[str, ...] = ("clean_description", "description_html")


@dataclass
class MatchStats:
    """Why a chunk's rows did not get an answer.

    ⚠ `echo_mismatch` and `unanswered` are the counters that REPLACED positional
    repair. They roll into `backfill_runs.errors` and also stand alone in the
    ledger, because "the model cannot echo ids at this batch size" and "the model
    dropped rows" have different remedies: the first is `--batch`, the second is
    a rerun."""

    echo_mismatch: int = 0
    unanswered: int = 0
    reasons: list[str] = field(default_factory=list)


def _coerce_tags(value: Any) -> list[str]:
    """enrichments.tags is a JSON array stored as TEXT. Never raise on it — a
    malformed tags column must cost the row its tag hints, not the whole run."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t) for t in value if isinstance(t, (str, int, float))]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(t) for t in parsed if isinstance(t, (str, int, float))]
    return []


def chunk_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Project selector rows onto the TRUSTED five-key shape.

    ⚠ Raises ValueError when a source row carries `clean_description` or
    `description_html`. The row handed to `build_subcategory_prompt` must have
    nowhere to put a description; this is the structural half of the injection
    boundary and the reason `rows_needing_subcategory` does not select one."""
    out: list[dict[str, Any]] = []
    for row in rows:
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        present = [k for k in _FORBIDDEN_SOURCE_KEYS if k in keys]
        if present:
            raise ValueError(
                f"chunk_rows: refusing a source row carrying {present} — the "
                f"backfill prompt must not be able to render a description "
                f"(see the module docstring's injection boundary)"
            )
        out.append(
            {
                "job_listing_id": row["job_listing_id"],
                "source_id": row["source_id"],
                "title": row["title"],
                "company": row["company"],
                "tags": _coerce_tags(row["tags"] if "tags" in keys else None),
            }
        )
    return out


def _echoed_pair(result: Any) -> tuple[str, str] | None:
    """The (source_id, job_listing_id) a result claims, or None when it does not
    unambiguously claim one. BOTH ids must be present AND non-empty strings."""
    if not isinstance(result, dict):
        return None
    sid, jid = result.get("source_id"), result.get("job_listing_id")
    if not isinstance(sid, str) or not sid.strip():
        return None
    if not isinstance(jid, str) or not jid.strip():
        return None
    return (sid, jid)


def match_results_to_chunk(
    chunk: list[dict[str, Any]], results: list[Any]
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], MatchStats]:
    """Match model results to chunk rows BY ECHOED PAIR — never by position.

    ⚠ This is the REPLACEMENT for positional repair, and the reason no
    `positional_repair_on_count_match` flag exists anywhere. Stamping identity by
    position assumes an order guarantee nothing provides; a reordered response
    writes row A's labels onto row B. Because the written value is non-NULL that
    row leaves the selector PERMANENTLY, a rerun cannot fix it, and the NULL
    tri-state cannot detect it. `ChunkEngine._call_with_repair` stamps identity
    only at `len(inputs) == 1 and len(results) == 1`; at batch > 1 each result
    must carry its own pair or it is dropped and counted.

    Returns (matched, stats) where matched is [(chunk_row, result), ...].

    ⚠ A DUPLICATE echoed pair drops BOTH the duplicate AND the already-matched
    result — a collapsed pair is not evidence for either row."""
    wanted = {(r["source_id"], r["job_listing_id"]): r for r in chunk}
    stats = MatchStats()
    matched: dict[tuple[str, str], dict[str, Any]] = {}
    collapsed: set[tuple[str, str]] = set()

    for result in results:
        pair = _echoed_pair(result)
        if pair is None:
            stats.echo_mismatch += 1
            stats.reasons.append("missing or non-string echoed id pair")
            continue
        if pair not in wanted:
            stats.echo_mismatch += 1
            stats.reasons.append(f"echoed pair {pair} is not in this chunk")
            continue
        if pair in collapsed:
            # already poisoned by an earlier duplicate; this one dies too
            stats.echo_mismatch += 1
            stats.reasons.append(f"echoed pair {pair} repeated again")
            continue
        if pair in matched:
            # ⚠ both die: a pair claimed twice is evidence for neither answer.
            del matched[pair]
            collapsed.add(pair)
            stats.echo_mismatch += 2
            stats.reasons.append(f"duplicate echoed pair {pair} — dropped BOTH")
            continue
        matched[pair] = result

    stats.unanswered = len(wanted) - len(matched)
    if stats.unanswered:
        stats.reasons.append(f"{stats.unanswered} chunk row(s) got no answer")
    return [(wanted[p], r) for p, r in matched.items()], stats


# ===========================================================================
# BF-9 — the night's label run
# ===========================================================================

# ⚠ A TRANSPORT failure does NOT bump attempts: a subscription rate-limit storm
# at 02:00 would otherwise retire thousands of perfectly good rows at the cap.
# After this many CONSECUTIVE transport failures the run aborts instead.
BACKFILL_TRANSPORT_ABORT = 5

# No breaker may fire before this many MODEL-ATTEMPTED rows — below it the rates
# are noise and a breaker would abort a healthy run on its first bad chunk.
BACKFILL_BREAKER_MIN_N = 50

# UNMEASURED — placeholder; set by BF-9
#   ⚠ Set from the 200-row CANARY's per-layer measurement, NOT from the
#   corpus-wide 41.2% `[]` rate. Layer 3 is by construction the residue where the
#   title says nothing and the tags disagree, so its true empty rate is far above
#   the corpus figure: a breaker tuned to 41% fires constantly, one tuned loose
#   misses real breakage. This breaker exists because `'[]'` is TERMINAL — a
#   systematically broken run does not error, it quietly writes "evaluated, no
#   specialty applies" on thousands of rows and removes them from the queue
#   permanently, recoverable only via BF-14.
BACKFILL_BREAKER_EMPTY_RATIO = 0.60

# UNMEASURED — placeholder; set by P0-5
#   ⚠ The batch at which the echo-mismatch rate starts rising is the CEILING on
#   `backfill:batch_size`, and this breaker is what makes that ceiling enforce
#   itself at 02:00. It is the operational replacement for positional repair.
BACKFILL_BREAKER_ECHO_RATIO = 0.20

# A cross-repo taxonomy drift, not a model problem. Fixed, not a placeholder:
# half the slugs being unknown to this repo cannot be anything else.
BACKFILL_BREAKER_INVALID_RATIO = 0.5

STOP_SENTINEL_NAME = ".backfill.stop"
BACKFILL_LOCK_NAME = ".backfill.lock"

# ⚠ P0-5 samples 20 rows; a whole-corpus `--dry-run` would otherwise write an
# 11k-entry JSON. The cap truncates the TAIL, and the head is deterministic
# across tiers (same selector, same order, and a dry run writes nothing), so two
# tiers' probes still describe the same rows.
PROBE_MAX_ROW_LABELS = 500


@dataclass
class BackfillOutcome:
    run_id: int | None = None
    status: str = "ok"
    aborted_reason: str | None = None
    notes: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    probe: dict[str, Any] | None = None
    exit_code: int = 0


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 3)


def run_backfill(
    store: Any,
    engine: Any,
    *,
    limit: int | None = None,
    batch: int | None = None,
    max_attempts: int | None = None,
    open_only: bool = False,
    deadline: Any = None,
    dry_run: bool = False,
    model: str | None = None,
    engine_name: str | None = None,
    probe_path: Any = None,
    clock: Any = None,
    stop_path: Any = None,
) -> BackfillOutcome:
    """The Tier-2 subcategory label run. ONE chunk at a time, forever sequential.

    ⚠ SEPARATION FROM THE LIVE LANE — four rules, and every one of them is a
    thing that already went wrong somewhere in this codebase:

    1. **Own single-flight lock.** The CLI takes `data/.backfill.lock`, never
       `.tick.lock` — taking the tick lock would block the live worker for the
       whole night.
    2. **This function NEVER calls `store.start_tick()` or
       `store.bump_tick_counters()`.** `bump_tick_counters` resolves
       `current_tick_id()` from meta, and the live worker restarts 62 s after
       each tick ends, so a tick is almost always OPEN — every counter the
       backfill bumped would be silently attributed to the LIVE tick, corrupting
       its metrics and the `drift_suspected` denominator, potentially forcing a
       healthy tick to close `status=error`. The ledger is `backfill_runs`.
    3. **It never writes chunk files.** Reusing the `classify-`/`judge-` prefixes
       would collide with a live tick's `_clear_chunks` glob.
    4. **It is NOT in `scripts/enrich_tick_wrapper.sh`.** It is launched by hand.

    ⚠ CONCURRENCY IS 1 AND THERE IS NO CONCURRENCY KNOB. `_call_with_repair` is
    strictly sequential (one `subprocess.run` per chunk, plus one on the repair
    path), nothing in `ChunkEngine` supports parallel chunks, and a threadpool
    would multiply SQLite write contention against the live tick, whose
    `busy_timeout` is 5000 ms. The draft's `--concurrency` flag and
    `backfill:concurrency` knob are DELETED. **The levers for wall time are
    `--batch` and the model tier, both measured by `P0-5`** — do not re-add the
    option on a slow night.

    ⚠ RESUMABILITY: there is nothing to implement. Unreached rows are still NULL
    with attempts unchanged, so the next run picks up exactly where this one
    stopped. No checkpoint file, no double-labelling.

    ⚠ DOCUMENTED, NOT FIXED: `prompts._taxonomy_text` is `lru_cache(maxsize=1)`,
    and this is the FIRST long-lived prompt-building process in the codebase, so
    it caches the rubric at first use and never sees a mid-run edit. That is the
    behaviour we want — the run row's `taxonomy_version` + `rubric_version`
    stamps prove which rubric produced the labels. After a rubric edit the runner
    must be RESTARTED, not just re-knobbed.
    """
    from datetime import datetime, timezone
    import time

    from job_enricher import enrich_config as ec
    from job_enricher import subcategory_rules as rules
    from job_enricher import taxonomy as tax
    from job_enricher.engines.base import EngineError

    clock = clock or (lambda: datetime.now(timezone.utc))
    batch = batch if batch is not None else ec.get_backfill_batch_size(store)
    max_attempts = (
        max_attempts if max_attempts is not None
        else ec.get_backfill_max_attempts(store)
    )
    stop_path = stop_path or (store.db_path.parent / STOP_SENTINEL_NAME)

    counters: dict[str, int] = dict.fromkeys(
        (
            "selected", "rule_labelled", "tag_labelled", "model_labelled",
            "empty_labelled", "nulled_slugs", "echo_mismatch", "unanswered",
            "transport_errors", "parse_errors", "errors", "retired",
            "model_calls",
        ),
        0,
    )
    chunk_latencies: list[float] = []
    # ⚠ P0-5's agreement half needs PER-ROW labels, not counters. Collected here
    # (see `_note_label`) so the dry-run probe can carry them; the real run's
    # labels are already in the DB.
    row_labels: list[dict[str, Any]] = []
    model_attempted = 0
    consecutive_transport = 0
    outcome = BackfillOutcome(counters=counters)
    started = clock()

    try:
        taxonomy_version = tax.taxonomy_version()
        rubric_version = tax.content_hash(tax.read_subcategory_rubric())
    except OSError:
        taxonomy_version = rubric_version = None

    run_id: int | None = None
    if not dry_run:
        run_id = store.start_backfill_run(
            kind="label", engine=engine_name or getattr(engine, "name", None),
            model=model, taxonomy_version=taxonomy_version,
            rubric_version=rubric_version,
            deadline_at=deadline.isoformat() if deadline is not None else None,
        )
    outcome.run_id = run_id

    def _bump(**kw: int) -> None:
        for key, value in kw.items():
            counters[key] = counters.get(key, 0) + value
        if run_id is not None:
            store.bump_backfill_counters(run_id, **kw)

    def _retires_at_cap(row: Any) -> bool:
        """⚠ THE LAST ATTEMPT, COUNTED AT THE MOMENT IT IS SPENT. The selector
        only returns rows with `subcategory_attempts < max_attempts`, so the
        failure bump this run is about to apply retires the row exactly when
        `attempts + 1 >= max_attempts`. This is the ONLY place the per-run
        `backfill_runs.retired` column can be filled: `subcategory_backlog_counts`
        computes a STANDING SNAPSHOT of every capped row in the corpus, which is a
        different number and cannot say which run spent the last attempt.

        ⚠ Counted under `--dry-run` too, exactly like `parse_errors`: the probe
        reports what the night WOULD retire."""
        try:
            attempts = int(row["subcategory_attempts"] or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            return False
        return attempts + 1 >= max_attempts

    def _note_label(row: Any, slugs: list[str] | None, source: str) -> None:
        """⚠ P0-5 AGREEMENT INPUT — and `source` is load-bearing. The rule pass is
        DETERMINISTIC and tier-independent, so counting rule-labelled rows in a
        haiku-vs-sonnet agreement would inflate it toward 100% with rows no model
        ever saw. `measure_subcategory_cost` compares `source == 'model'` only."""
        if len(row_labels) >= PROBE_MAX_ROW_LABELS:
            return
        row_labels.append({
            "source_id": row["source_id"],
            "job_listing_id": row["job_listing_id"],
            "slugs": list(slugs or []),
            "source": source,
        })

    def _finish(status: str, reason: str | None, notes: str | None, code: int):
        outcome.status = status
        outcome.aborted_reason = reason
        outcome.notes = notes
        outcome.exit_code = code
        if run_id is not None:
            store.end_backfill_run(run_id, status, aborted_reason=reason, notes=notes)
        outcome.probe = _build_probe(
            counters, chunk_latencies, model_attempted,
            (clock() - started).total_seconds(), status, reason,
            row_labels,
        )
        if dry_run and probe_path is not None:
            probe_path.parent.mkdir(parents=True, exist_ok=True)
            probe_path.write_text(
                json.dumps(outcome.probe, indent=2), encoding="utf-8"
            )
        return outcome

    remaining = limit
    # ⚠ DRY-RUN PAGING, NOT DRY-RUN FILTERING. A dry run writes nothing, so a
    # written row never stops being NULL and the claim-free selector hands back
    # the SAME leading rows forever. In the real run the write IS the cursor;
    # here `seen` is the cursor, and it must make the run PAGE PAST the rows it
    # has already processed — over-fetch by len(seen) and drop the prefix.
    # ⚠ FILTERING THE SELECTOR'S RESULT INSTEAD IS A SILENT ONE-CHUNK RUN: pass 2
    # re-selects the same `take` rows, every one of them is in `seen`, the list
    # comes back empty and the loop exits `status='ok'` with
    # "queue exhausted (dry-run)". That defeats BF-9's "--dry-run runs the FULL
    # pipeline" (one latency sample, so p50 == p95 == max), makes P0-5's sweep
    # measure `batch` rows per cell instead of `--n`, and shrinks the runbook's
    # `--dry-run --limit 20` smoke test to one chunk.
    seen: set[tuple[str, str]] = set()
    while True:
        # (a) the DB kill switch, honoured at CHUNK granularity (seconds, not a
        #     signal). Skipped under --dry-run: the pre-flight smoke test runs
        #     BEFORE the knob is flipped on, and a dry run writes nothing.
        if not dry_run and not ec.get_backfill_enabled(store):
            return _finish("ok", None, "stopped: backfill:enabled is off", 0)
        # (b) the INSTANT kill switch — no DB write needed to trip it
        try:
            if stop_path.exists():
                return _finish("ok", None, f"stopped: {stop_path.name} sentinel", 0)
        except OSError:
            pass
        # (c) the wall-clock deadline. ⚠ CHECKED BETWEEN CHUNKS ONLY, so a chunk
        #     in flight always completes its write and is never killed mid-write.
        if deadline is not None and clock() >= deadline:
            return _finish("ok", None, "deadline", 0)

        take = batch if remaining is None else min(batch, remaining)
        if take <= 0:
            return _finish("ok", None, "limit reached", 0)
        rows = store.rows_needing_subcategory(
            # the dry run's window has to clear the `seen` prefix, or it re-reads
            # the same head of the queue on every pass. The real run asks for
            # exactly `take` — its writes retire the rows it has done.
            limit=take + len(seen) if dry_run else take,
            max_attempts=max_attempts, open_only=open_only,
        )
        if not rows:
            return _finish("ok", None, "queue empty", 0)
        if dry_run:
            rows = [
                r for r in rows
                if (r["source_id"], r["job_listing_id"]) not in seen
            ][:take]
            if not rows:
                return _finish("ok", None, "queue exhausted (dry-run)", 0)
            seen.update((r["source_id"], r["job_listing_id"]) for r in rows)
        if remaining is not None:
            remaining -= len(rows)
        _bump(selected=len(rows))

        # (e) THE FREE RULE PASS. Rows the deterministic title/tag regex resolves
        #     are written immediately at ZERO model cost and never reach the model.
        pending: list[Any] = []
        for row in rows:
            slugs, layer = rules.rule_label(
                row["title"], _coerce_tags(row["tags"] if "tags" in row.keys() else None)
            )
            if not slugs:
                pending.append(row)
                continue
            if not dry_run:
                store.record_subcategories(
                    row["source_id"], row["job_listing_id"], slugs,
                    confidence=None, source="rule", run_id=run_id,
                )
            _bump(**{"rule_labelled" if layer == "title" else "tag_labelled": 1})
            _note_label(row, slugs, "rule")

        if not pending:
            continue

        # (f) the trusted five-key projection, then ONE model call
        chunk = chunk_rows(pending)
        by_pair = {(r["source_id"], r["job_listing_id"]): r for r in pending}
        t0 = time.monotonic()
        try:
            results = engine.subcategory(chunk)
        except (EngineError, OSError) as exc:
            # ⚠ TRANSPORT: attempts are NOT bumped.
            consecutive_transport += 1
            _bump(transport_errors=1, errors=1)
            logger.warning(
                "subcategory-backfill: transport failure %d/%d: %s",
                consecutive_transport, BACKFILL_TRANSPORT_ABORT, exc,
            )
            if consecutive_transport >= BACKFILL_TRANSPORT_ABORT:
                return _finish(
                    "aborted", "transport",
                    f"{BACKFILL_TRANSPORT_ABORT} consecutive transport failures; "
                    f"no row's attempts were bumped",
                    1,
                )
            continue
        chunk_latencies.append(time.monotonic() - t0)
        consecutive_transport = 0
        _bump(model_calls=1)
        model_attempted += len(chunk)

        # (g) echoed-pair matching — NO positional stamping, ever
        matched, stats = match_results_to_chunk(chunk, results)
        if stats.echo_mismatch:
            _bump(echo_mismatch=stats.echo_mismatch, errors=stats.echo_mismatch)
        if stats.unanswered:
            _bump(unanswered=stats.unanswered, errors=stats.unanswered)

        answered = {(r["source_id"], r["job_listing_id"]) for r, _ in matched}
        for pair, row in by_pair.items():
            if pair in answered:
                continue
            # ⚠ unanswered / echo-mismatch rows take the PARSE-FAILURE
            # disposition: attempts bumped, subcategories left NULL. NEVER an
            # empty-array write (that is TERMINAL) and never a transport
            # disposition (that would not bump attempts at all).
            _bump(parse_errors=1)
            if _retires_at_cap(row):
                _bump(retired=1)
            if not dry_run:
                store.record_subcategory_failure(row["source_id"], row["job_listing_id"])

        # (h) validate, (i) write
        for row, result in matched:
            # `row` is the FIVE-KEY projection; the resolved category lives on
            # the selector row, which the projection deliberately cannot carry.
            source_row = by_pair[(row["source_id"], row["job_listing_id"])]
            raw = result.get("subcategories")
            slugs, bad, _warn = tax.validate_subcategories(
                source_row["category"], raw
            )
            if bad:
                _bump(nulled_slugs=len(bad))
            if slugs is None or (bad and not slugs):
                # ⚠ ALL slugs invalid (or a leak-rule rejection): the FAILURE
                # disposition. Stay NULL — never write [] on a failure.
                _bump(parse_errors=1)
                if _retires_at_cap(source_row):
                    _bump(retired=1)
                if not dry_run:
                    store.record_subcategory_failure(
                        row["source_id"], row["job_listing_id"]
                    )
                continue
            conf = result.get("subcategory_confidence")
            if not isinstance(conf, (int, float)) or isinstance(conf, bool):
                conf = None
            if not dry_run:
                store.record_subcategories(
                    row["source_id"], row["job_listing_id"], slugs,
                    confidence=conf, source="backfill", run_id=run_id,
                )
            _bump(**{"empty_labelled" if not slugs else "model_labelled": 1})
            _note_label(row, slugs, "model")

        # ⚠ THREE IN-FLIGHT BREAKERS, all armed only past BACKFILL_BREAKER_MIN_N
        # MODEL-ATTEMPTED rows.
        if model_attempted >= BACKFILL_BREAKER_MIN_N:
            empty_rate = counters["empty_labelled"] / model_attempted
            invalid_rate = counters["nulled_slugs"] / model_attempted
            echo_rate = counters["echo_mismatch"] / model_attempted
            if empty_rate > BACKFILL_BREAKER_EMPTY_RATIO:
                return _finish(
                    "aborted", "empty_rate",
                    f"empty-array rate {empty_rate:.2%} over {model_attempted} "
                    f"model-attempted rows exceeds "
                    f"{BACKFILL_BREAKER_EMPTY_RATIO:.0%}; ⚠ '[]' is TERMINAL — "
                    f"the {counters['empty_labelled']} rows already written have "
                    f"LEFT the queue and need `cli subcategory-reset --run-id "
                    f"{run_id}`",
                    1,
                )
            if invalid_rate > BACKFILL_BREAKER_INVALID_RATIO:
                return _finish(
                    "aborted", "invalid_slugs",
                    f"invalid-slug rate {invalid_rate:.2%} — this is CROSS-REPO "
                    f"TAXONOMY DRIFT, not a model problem; run `cli parity-check`",
                    1,
                )
            if echo_rate > BACKFILL_BREAKER_ECHO_RATIO:
                return _finish(
                    "aborted", "echo_mismatch",
                    f"echo-mismatch rate {echo_rate:.2%} at batch={batch} — the "
                    f"model cannot echo ids reliably at this batch size. LOWER "
                    f"`--batch`; do not rerun at the same size",
                    1,
                )


def _build_probe(
    counters: dict[str, int],
    chunk_latencies: list[float],
    model_attempted: int,
    wall_s: float,
    status: str,
    aborted_reason: str | None,
    row_labels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The `--dry-run` artifact. ⚠ P0-5 measures with THIS harness rather than
    shipping a second one, so the probe and the real run cannot diverge.

    ⚠ `row_labels` IS THE AGREEMENT INPUT and without it P0-5's decision rule is
    HALF INERT: `tier_agreement` has no source, the '⚠ below 85% agreement,
    SONNET WINS' branch can never fire, and the rule silently collapses to
    'lowest p95 subject to parse-failure <= 2%' — which would pick a cheap tier
    that disagrees with sonnet on 40% of rows. Each entry carries its `source`
    because the rule pass is tier-independent and must NOT count."""
    labelled = counters["model_labelled"] + counters["empty_labelled"]
    rule_total = counters["rule_labelled"] + counters["tag_labelled"]
    return {
        "status": status,
        "aborted_reason": aborted_reason,
        "wall_seconds": round(wall_s, 3),
        "counters": dict(counters),
        "model_calls": counters["model_calls"],
        "model_attempted_rows": model_attempted,
        "chunk_latency_s": {
            "p50": _percentile(chunk_latencies, 50),
            "p95": _percentile(chunk_latencies, 95),
            "max": round(max(chunk_latencies), 3) if chunk_latencies else None,
        },
        # the number P0-5's decision rule reads
        "seconds_per_row": (
            round(sum(chunk_latencies) / model_attempted, 3)
            if model_attempted else None
        ),
        # ⚠ split by LAYER. The tag layer is the enricher's OWN v6 output, not
        # company tags — see this module's docstring. Not independent evidence.
        "rule_pass": {
            "title_layer": counters["rule_labelled"],
            "tag_layer": counters["tag_labelled"],
            "total": rule_total,
            "yield": (
                round(rule_total / counters["selected"], 4)
                if counters["selected"] else None
            ),
        },
        "empty_array_rate": (
            round(counters["empty_labelled"] / model_attempted, 4)
            if model_attempted else None
        ),
        "invalid_slug_rate": (
            round(counters["nulled_slugs"] / model_attempted, 4)
            if model_attempted else None
        ),
        "echo_mismatch_rate": (
            round(counters["echo_mismatch"] / model_attempted, 4)
            if model_attempted else None
        ),
        "labelled_rows": labelled,
        # ⚠ THE PER-ROW LABELS P0-5's agreement half is computed from.
        "row_labels": list(row_labels or []),
        "row_labels_truncated": len(row_labels or []) >= PROBE_MAX_ROW_LABELS,
    }


# ===========================================================================
# BF-16 — measure the per-request write-back cost and DERIVE the drain pace
# ===========================================================================
# ⚠ THE RATE AT WHICH THE DRAIN MAY PUSH MUST BE DERIVED FROM A MEASURED
# PER-REQUEST COST, NOT INVENTED. The draft's "200 per tick" was a guess, and it
# is the number that produced the two-week lag.

# `SCHEMA-14` 422s above this many items.
SCHEMA_14_MAX_ITEMS = 500

PUSH_PROBE_DEFAULT_SIZES: tuple[int, ...] = (50, 100, 250, 500)

# UNMEASURED — placeholder; set by BF-16
#   ⚠ THE PUSH BATCH IS THE LARGEST B WHOSE MEASURED `S_p95` STAYS UNDER THIS —
#   batch size is capped by SLOT-HOLD TIME, not by request count, which is the
#   opposite of the usual instinct. 5.0 s sits inside the pool semaphore's 5 s
#   acquire timeout (dependencies.py:88), so the drain can never be the request
#   that pushes another request past it. Confirm against BF-16's distribution.
PUSH_SLOT_HOLD_CEILING_S = 5.0

# UNMEASURED — placeholder; set by BF-16
#   The real value is `max(30.0, 3 * T_req_p95)` — see `push_http_timeout_s`.
#   ⚠ At the default `http_timeout_seconds = 30.0` a slow batch times out
#   CLIENT-side while the server keeps holding its pooled slot, and an immediate
#   retry then stacks a second slot. That is the exact way a throttle turns into
#   the 2026-05-17 incident.
PUSH_HTTP_TIMEOUT_S = 30.0


def push_http_timeout_s(t_req_p95: float | None) -> float:
    """`max(30.0, 3 x T_req_p95)`, passed to `JVNClient(timeout=...)`."""
    if not t_req_p95:
        return PUSH_HTTP_TIMEOUT_S
    return max(PUSH_HTTP_TIMEOUT_S, 3.0 * float(t_req_p95))


def derive_pace(
    slot_hold_p95: float, batch: int, duty_pct: int, pending_push: int
) -> dict[str, float | int | None]:
    """The three derived numbers, computed and PRINTED at runtime, never baked in.

    ⚠ At concurrency 1 the drain occupies at most ONE of the pool's 15 slots at
    any instant and, time-averaged, `duty_pct/100` of one slot. The 2026-05-17
    incident established the violated invariant as "N parallel DB-backed requests
    must stay <= the pool slot count"; `init_pool(dsn, minconn=1, maxconn=15,
    timeout=5.0)` and `semaphore.acquire(timeout=_pool_timeout)` are the code.
    N=1 satisfies it STRUCTURALLY; the duty cap bounds time-averaged occupancy on
    top of that."""
    if not slot_hold_p95 or duty_pct <= 0:
        return {
            "sleep_between_batches": None, "rows_per_hour": None,
            "eta_hours": None, "pending_push": pending_push,
        }
    sleep = slot_hold_p95 * (100.0 / duty_pct - 1.0)
    rows_per_hour = 3600.0 * batch * (duty_pct / 100.0) / slot_hold_p95
    return {
        "sleep_between_batches": round(sleep, 3),
        "rows_per_hour": round(rows_per_hour, 1),
        "eta_hours": (
            round(pending_push / rows_per_hour, 2) if rows_per_hour else None
        ),
        "pending_push": pending_push,
    }


def push_probe(
    store: Any,
    client: Any,
    *,
    batches: int = 3,
    sizes: tuple[int, ...] = PUSH_PROBE_DEFAULT_SIZES,
    duty_pct: int = 25,
    timer: Any = None,
) -> dict[str, Any]:
    """Measure `T_req(B)`, `T_ping`, `S(B)` and `bytes(B)` against PROD JVN.

    ⚠ IT IS A MEASUREMENT, NOT A PUSH. Every POST re-writes rows JVN already
    holds, so each one is idempotent, and nothing local is stamped —
    `subcategory_sent_at` is untouched by construction (this function never calls
    `mark_subcategory_sent`).

    ⚠ `S(B) = T_req_p95 - T_ping_p50` is the estimated POOL-SLOT HOLD TIME, and
    it — not the request count — is the number that matters: the endpoint takes
    ONE pooled connection via `Depends(get_db)` for the WHOLE batch and commits
    once at the end, so slot occupancy scales with BATCH SIZE, not with how many
    requests you make.

    ⚠ STRICTLY SEQUENTIAL. Requests must never overlap; the probe's own test
    asserts monotonic non-overlap of request timestamps."""
    import time

    timer = timer or time.monotonic
    rows = store.rows_needing_subcategory_push(limit=max(sizes))
    items = [push_item(r) for r in rows]

    ping_times: list[float] = []
    for _ in range(batches):
        t0 = timer()
        client.get_health()
        ping_times.append(timer() - t0)
    t_ping_p50 = _percentile(ping_times, 50) or 0.0

    cells: dict[str, Any] = {}
    for size in sizes:
        payload = items[:size]
        if not payload:
            cells[str(size)] = {
                "n": 0, "note": "no rows available locally to re-write",
                "t_req_p50": None, "t_req_p95": None, "t_req_max": None,
                "slot_hold_p95": None, "bytes": None,
            }
            continue
        blob_bytes = len(json.dumps({"items": payload}).encode("utf-8"))
        times: list[float] = []
        for _ in range(batches):
            t0 = timer()
            client.post_subcategories(payload)
            times.append(timer() - t0)
        p95 = _percentile(times, 95)
        cells[str(size)] = {
            "n": len(payload),
            "t_req_p50": _percentile(times, 50),
            "t_req_p95": p95,
            "t_req_max": round(max(times), 3),
            # S(B) — the estimated pool-slot hold time
            "slot_hold_p95": round(max(0.0, (p95 or 0.0) - t_ping_p50), 3),
            "bytes": blob_bytes,
        }

    chosen = choose_push_batch(cells)
    pending = store.subcategory_backlog_counts().get("pending_push", 0)
    slot_hold = (
        cells[str(chosen)]["slot_hold_p95"] if chosen and str(chosen) in cells else None
    )
    return {
        "measured_at": _now_iso(),
        "t_ping_p50": t_ping_p50,
        "cells": cells,
        "chosen_batch": chosen,
        "chosen_reason": (
            f"largest B whose S_p95 stays under PUSH_SLOT_HOLD_CEILING_S="
            f"{PUSH_SLOT_HOLD_CEILING_S}s (hard ceiling {SCHEMA_14_MAX_ITEMS}: "
            f"SCHEMA-14 422s above it)"
        ),
        "duty_pct": duty_pct,
        "push_http_timeout_s": push_http_timeout_s(
            cells[str(chosen)]["t_req_p95"] if chosen and str(chosen) in cells else None
        ),
        "derived": derive_pace(slot_hold or 0.0, chosen or 0, duty_pct, pending),
    }


def choose_push_batch(cells: dict[str, Any]) -> int | None:
    """⚠ The LARGEST B whose `S_p95` stays under `PUSH_SLOT_HOLD_CEILING_S`."""
    ok = [
        int(b) for b, cell in cells.items()
        if cell.get("slot_hold_p95") is not None
        and cell["slot_hold_p95"] < PUSH_SLOT_HOLD_CEILING_S
        and int(b) <= SCHEMA_14_MAX_ITEMS
    ]
    return max(ok) if ok else None


def slot_hold_from_probe(
    report: dict[str, Any], batch: int | None = None
) -> tuple[float | None, float | None, str]:
    """Read `BF-16`'s MEASURED `S_p95` (and `T_req_p95`) out of a probe report.

    ⚠ THE SEAM THIS EXISTS TO CLOSE. Without it `subcategory-push` computes its
    sleep, rows/hour and ETA from `PUSH_SLOT_HOLD_CEILING_S = 5.0` — an
    UNMEASURED PLACEHOLDER — no matter what the probe measured, so an operator
    who runs `subcategory-push-probe`, fills in the runbook table and then runs
    the push reads an ETA that is unrelated to their own measurement. `BF-12b`'s
    contract is 'all derived from BF-16's measurement — nothing invented'.

    Returns `(slot_hold_p95, t_req_p95, note)`. Both values are None when the
    report carries no usable cell — ⚠ the caller must REFUSE rather than fall
    back to the placeholder, because a silent fallback is the defect itself.

    `batch` picks the cell; without it, the probe's own `chosen_batch` wins."""
    cells = report.get("cells") or {}
    key = str(batch) if batch is not None else str(report.get("chosen_batch"))
    cell = cells.get(key)
    if cell is None:
        return None, None, f"no cell for B={key} in the probe (have: {sorted(cells)})"
    hold = cell.get("slot_hold_p95")
    if hold is None:
        return None, None, f"cell B={key} has no measured slot_hold_p95"
    return (
        float(hold),
        (float(cell["t_req_p95"]) if cell.get("t_req_p95") is not None else None),
        f"measured S_p95={hold}s at B={key} (probe {report.get('measured_at')})",
    )


def push_item(row: Any) -> dict[str, Any]:
    """The SLIM payload item — ⚠ EXACTLY six keys, because `SCHEMA-14` is
    `extra='forbid'` and an unknown key 422s the whole batch.

    `taxonomy_version` is the version that produced the SUBCATEGORY, which is not
    always the row's classify-time version: for a backfilled row it comes from the
    run ledger (joined in by `rows_needing_subcategory_push`), and only for a
    classify/judge-lane label is `enrichments.taxonomy_version` the right stamp."""
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    version = None
    if "run_taxonomy_version" in keys:
        version = row["run_taxonomy_version"]
    if not version and "taxonomy_version" in keys:
        version = row["taxonomy_version"]
    raw = row["subcategories"]
    try:
        subcats = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        subcats = None
    return {
        "source_id": row["source_id"],
        "job_listing_id": row["job_listing_id"],
        "subcategories": subcats,
        "subcategory_confidence": row["subcategory_confidence"],
        "subcategory_source": row["subcategory_source"],
        "taxonomy_version": version,
    }


PUSH_ITEM_KEYS: frozenset[str] = frozenset(
    {
        "source_id", "job_listing_id", "subcategories",
        "subcategory_confidence", "subcategory_source", "taxonomy_version",
    }
)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# BF-12b — the throttled bulk drain to JVN
# ===========================================================================
# ⚠ THE D2 RULING, APPLIED. Two designs were deleted to get here.
#
# (1) The draft's `subcategory-reopen` drain — `record_subcategories(reopen=True)`,
#     the `writeback:subcategory_reopen_per_run` knob and the tick-wrapper edit —
#     is DELETED, for three verified reasons:
#       (a) clearing `sent_at` puts the drained rows into `enriched_unsent()`,
#           which takes `limit=None`, so the next tick's `write_back` ships an
#           UNBOUNDED burst the drain cannot pace;
#       (b) riding the tick caps the drain at one slice per tick, and at ~12.8
#           ticks/day THAT is the two-week lag;
#       (c) re-opening flips `inbox.status` back to 'enriched', so a drained row
#           is temporarily indistinguishable from a genuinely unshipped one and
#           the poison-row `attempts` machinery starts counting drain failures
#           against real rows.
#
# (2) Its replacement — re-POSTing the full `/results` payload minus the two
#     locations keys — is ALSO deleted. `apply_result` returns early for any row
#     with `human_corrected_at` set WHILE STILL COUNTING IT `written`, so the
#     `/results` route can NEVER write a backfilled label onto the human-corrected
#     pool the eval loop depends on — and it re-ships every row's full
#     `clean_description` to set two columns. `SCHEMA-14` skips only on
#     `enrichment_subcategory_source='human'` and holds one pooled connection for
#     two narrow UPDATEs.

# ⚠ NAMED, DIRECT HONOURING of docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md:
# a 5xx whose body carries this EXACT string is the failure signature the
# incident established (raised at dependencies.py:89).
PUSH_POOL_PRESSURE_STRING = "Timed out waiting for a database connection"
PUSH_POOL_ABORT = 3

# ⚠ The server may still be committing and holding its slot; an immediate retry
# after a client-side timeout stacks a SECOND slot.
PUSH_TIMEOUT_COOLDOWN = 30.0

# The adaptive backoff's ceiling and its decay back toward the derived sleep.
PUSH_MAX_SLEEP = 60.0
PUSH_SLEEP_DECAY = 0.8

PUSH_LOCK_NAME = ".subcategory-push.lock"
PUSH_STOP_SENTINEL_NAME = ".subcategory-push.stop"


@dataclass
class PushOutcome:
    run_id: int | None = None
    status: str = "ok"
    aborted_reason: str | None = None
    notes: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    effective_sleep: float = 0.0
    plan: dict[str, Any] = field(default_factory=dict)
    exit_code: int = 0


def push_subcategories(
    store: Any,
    client: Any = None,
    *,
    limit: int | None = None,
    batch: int | None = None,
    duty_pct: int | None = None,
    max_seconds: int | None = None,
    slot_hold_p95: float | None = None,
    t_req_p95: float | None = None,
    dry_run: bool = False,
    sleep: Any = None,
    timer: Any = None,
    stop_path: Any = None,
    max_retries: int = 3,
    printer: Any = print,
) -> PushOutcome:
    """Drain labelled rows to JVN — paced, resumable, and never touching the
    live write-back's lane.

    ⚠ CONCURRENCY IS HARD-CODED 1 AND THERE IS NO KNOB. One in-flight request =
    one of the pool's 15 slots. `docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md`
    established the violated invariant as "N parallel DB-backed requests must stay
    <= the pool slot count"; `init_pool(dsn, minconn=1, maxconn=15, timeout=5.0)`
    and `semaphore.acquire(timeout=_pool_timeout)` are the code. **N=1 satisfies
    it structurally and MUST NOT be traded for speed.**

    ⚠ RESUMABILITY: `subcategory_sent_at` IS the cursor. No offset, no
    checkpoint — re-running after any interruption resumes exactly.

    ⚠ THE ETA IS PRINTED BEFORE THE FIRST POST. If it is unacceptable the lever
    is `duty_pct`, and raising it is a deliberate, logged act. That ETA is what
    replaces "overnight" as this plan's stated claim."""
    import time

    import httpx

    from job_enricher import enrich_config as ec
    from job_enricher.jvn_client import JVNClient
    from job_enricher.writeback import TRANSIENT_HTTP_STATUSES, _match_failed_pairs

    sleep = sleep or time.sleep
    timer = timer or time.monotonic
    stop_path = stop_path or (store.db_path.parent / PUSH_STOP_SENTINEL_NAME)

    # ⚠ REFUSES when the write-back knob is OFF. Draining while JVN is not
    # accepting the facet would stamp the cursor on rows nothing received.
    if not ec.get_writeback_send_subcategories(store):
        return PushOutcome(
            status="refused",
            notes="writeback:send_subcategories is OFF — nothing was posted",
            exit_code=2,
        )

    batch = batch if batch is not None else ec.get_subcategory_push_batch(store)
    duty_pct = (
        duty_pct if duty_pct is not None else ec.get_subcategory_push_duty_pct(store)
    )
    max_seconds = (
        max_seconds if max_seconds is not None
        else ec.get_subcategory_push_max_seconds(store)
    )
    client = client or JVNClient(timeout=push_http_timeout_s(t_req_p95))

    pending = store.subcategory_backlog_counts().get("pending_push", 0)
    # ⚠ MEASURED OR LOUDLY NOT. Everything below — sleep, rows/hour, ETA — is a
    # function of this one number, so a silent fall back to the UNMEASURED
    # `PUSH_SLOT_HOLD_CEILING_S` placeholder would print an ETA the operator has
    # every reason to read as BF-16's answer. Pass `--slot-hold` or `--probe`.
    measured = slot_hold_p95 is not None
    hold = slot_hold_p95 if measured else PUSH_SLOT_HOLD_CEILING_S
    plan = derive_pace(hold, batch, duty_pct, pending)
    plan["batch"] = batch
    plan["duty_pct"] = duty_pct
    plan["slot_hold_p95_used"] = hold
    plan["slot_hold_measured"] = measured
    plan["slot_hold_source"] = (
        "BF-16 measurement" if measured
        else f"UNMEASURED PUSH_SLOT_HOLD_CEILING_S={PUSH_SLOT_HOLD_CEILING_S}s placeholder"
    )
    plan["http_timeout_s"] = push_http_timeout_s(t_req_p95)
    plan["max_seconds"] = max_seconds
    printer(
        f"subcategory-push: batch={batch} duty={duty_pct}% "
        f"sleep={plan['sleep_between_batches']}s "
        f"rows_per_hour={plan['rows_per_hour']} pending_push={pending} "
        f"ETA={plan['eta_hours']}h (max_seconds={max_seconds})"
    )
    printer(
        f"  S_p95={hold}s from {plan['slot_hold_source']}; "
        f"http_timeout={plan['http_timeout_s']}s"
    )
    if not measured:
        printer(
            "⚠ THE SLEEP, ROWS/HOUR AND ETA ABOVE ARE NOT MEASURED. They are "
            "derived from the placeholder ceiling, not from BF-16. Re-run with "
            "`--probe <subcategory-push-probe-*.json>` or `--slot-hold <S_p95>`."
        )

    counters: dict[str, int] = dict.fromkeys(
        (
            "pushed", "push_batches", "push_rejected", "push_skipped_human",
            "push_nulled_by_jvn", "pool_pressure_events", "errors",
        ),
        0,
    )
    outcome = PushOutcome(counters=counters, plan=plan)
    base_sleep = float(plan["sleep_between_batches"] or 0.0)
    current_sleep = base_sleep
    pool_events = 0
    started = timer()

    run_id = None if dry_run else store.start_backfill_run(kind="push")
    outcome.run_id = run_id

    def _bump(**kw: int) -> None:
        for key, value in kw.items():
            counters[key] = counters.get(key, 0) + value
        if run_id is not None:
            store.bump_backfill_counters(run_id, **kw)

    def _finish(status: str, reason: str | None, notes: str | None, code: int):
        outcome.status = status
        outcome.aborted_reason = reason
        outcome.notes = notes
        outcome.exit_code = code
        outcome.effective_sleep = current_sleep
        if run_id is not None:
            # ⚠ The effective sleep AT THE END of the run rides in `notes` so the
            # morning report can show an adaptive backoff that never decayed.
            store.end_backfill_run(
                run_id, status, aborted_reason=reason,
                notes=(
                    f"{notes} | " if notes else ""
                ) + f"effective_sleep={round(current_sleep, 3)}s",
            )
        return outcome

    remaining = limit
    while True:
        try:
            if stop_path.exists():
                return _finish("ok", None, f"stopped: {stop_path.name} sentinel", 0)
        except OSError:
            pass
        if max_seconds and (timer() - started) >= max_seconds:
            return _finish("ok", None, "max_seconds reached", 0)

        take = batch if remaining is None else min(batch, remaining)
        if take <= 0:
            return _finish("ok", None, "limit reached", 0)
        rows = store.rows_needing_subcategory_push(limit=take)
        if not rows:
            return _finish("ok", None, "nothing left to push", 0)
        if remaining is not None:
            remaining -= len(rows)

        chunk_pairs = [(r["source_id"], r["job_listing_id"]) for r in rows]
        # ⚠ EXACTLY the six slim keys — SCHEMA-14 is extra='forbid'.
        items = [push_item(r) for r in rows]
        if dry_run:
            _bump(push_batches=1)
            printer(f"subcategory-push: --dry-run would post {len(items)} items")
            if remaining is None:
                return _finish("ok", None, "dry-run", 0)
            continue

        result: dict[str, Any] | None = None
        for attempt in range(max_retries):
            try:
                result = client.post_subcategories(items)
                break
            except httpx.HTTPStatusError as exc:
                status_code = (
                    exc.response.status_code if exc.response is not None else None
                )
                body = ""
                try:
                    body = exc.response.text if exc.response is not None else ""
                except Exception:  # pragma: no cover - defensive
                    body = ""
                if (
                    status_code is not None and status_code >= 500
                    and PUSH_POOL_PRESSURE_STRING in body
                ):
                    # ⚠ THE 2026-05-17 FAILURE SIGNATURE, by name.
                    pool_events += 1
                    _bump(pool_pressure_events=1, errors=1)
                    current_sleep = min(
                        PUSH_MAX_SLEEP, max(current_sleep, 1.0) * 2.0
                    )
                    logger.error(
                        "subcategory-push: POOL PRESSURE %d/%d — sleep now %.1fs",
                        pool_events, PUSH_POOL_ABORT, current_sleep,
                    )
                    if pool_events >= PUSH_POOL_ABORT:
                        return _finish(
                            "aborted", "pool_pressure",
                            f"{pool_events} pool-pressure events — the drain saw "
                            f"the 2026-05-17 failure signature. Do NOT raise "
                            f"duty_pct to catch up: LOWER the batch, confirm JVN "
                            f"is healthy, resume (the drain is resumable).",
                            1,
                        )
                    sleep(current_sleep)
                    continue
                if status_code in TRANSIENT_HTTP_STATUSES:
                    # ⚠ ADAPTIVE BACKOFF. A per-batch retry alone keeps arriving
                    # at the same rate, which is precisely wrong when the far side
                    # is under pressure.
                    current_sleep = min(
                        PUSH_MAX_SLEEP, max(current_sleep, 1.0) * 2.0
                    )
                    _bump(errors=1)
                    logger.warning(
                        "subcategory-push: transient HTTP %s (attempt %d/%d); "
                        "sleep now %.1fs", status_code, attempt + 1, max_retries,
                        current_sleep,
                    )
                    if attempt < max_retries - 1:
                        sleep(2 ** attempt)
                    continue
                # ⚠ A non-transient 4xx (413/422 included) means a KNOB is
                # mis-set. Retrying cannot help; abort immediately.
                return _finish(
                    "aborted", "http_error",
                    f"non-transient HTTP {status_code} — a knob is mis-set "
                    f"(413/422 = batch too large or an extra payload key against "
                    f"extra='forbid'); retrying cannot help",
                    1,
                )
            except httpx.TimeoutException as exc:
                _bump(errors=1)
                logger.warning(
                    "subcategory-push: CLIENT-side timeout (attempt %d/%d): %s — "
                    "waiting %.0fs; the server may still be committing and "
                    "holding its slot", attempt + 1, max_retries, exc,
                    PUSH_TIMEOUT_COOLDOWN,
                )
                sleep(PUSH_TIMEOUT_COOLDOWN)
                continue
            except httpx.RequestError as exc:
                _bump(errors=1)
                logger.warning("subcategory-push: transport error: %s", exc)
                if attempt < max_retries - 1:
                    sleep(2 ** attempt)
                continue

        if result is None:
            return _finish(
                "aborted", "transport",
                f"batch of {len(items)} never got a 2xx after {max_retries} "
                f"attempts; no row was stamped, so the next run retries them",
                1,
            )

        _bump(push_batches=1)
        # ⚠ REUSED VERBATIM so the ambiguous-bare-id semantics are IDENTICAL to
        # the live write-back's rather than re-derived here.
        rejected, ambiguous = _match_failed_pairs(
            result.get("failed") or [], chunk_pairs
        )
        skipped_human = _human_skipped_pairs(result.get("skipped") or [], chunk_pairs)
        nulled = _nulled_warning_count(result.get("warnings") or [])
        if nulled:
            _bump(push_nulled_by_jvn=nulled)
            logger.warning(
                "subcategory-push: JVN NULLED %d subcategory value(s) — the "
                "cross-repo 15-slug parity is BROKEN; run `cli parity-check`",
                nulled,
            )
        # ⚠ A human-lock skip DOES stamp: it is TERMINAL, not a retryable failure.
        stamped = [
            p for p in chunk_pairs
            if p not in rejected and p not in ambiguous
        ]
        store.mark_subcategory_sent(stamped)
        _bump(
            pushed=len(stamped) - len(skipped_human),
            push_skipped_human=len(skipped_human),
            push_rejected=len(rejected) + len(ambiguous),
        )

        # ⚠ decay 20% back toward the derived sleep after a clean batch
        if not rejected and not nulled:
            current_sleep = max(base_sleep, current_sleep * PUSH_SLEEP_DECAY)
        if current_sleep:
            sleep(current_sleep)


def _human_skipped_pairs(skipped: list[Any], chunk_pairs: list[tuple[str, str]]):
    """`skipped[]` entries naming the PER-FIELD human lock."""
    out = []
    known = set(chunk_pairs)
    for item in skipped:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or item.get("skipped") or "")
        if "human" not in reason.lower():
            continue
        pair = (item.get("source_id"), item.get("job_listing_id"))
        if pair in known:
            out.append(pair)
    return out


def _nulled_warning_count(warnings: list[Any]) -> int:
    """⚠ Non-zero means the cross-repo 15-slug parity is broken, and the morning
    report must say so rather than burying it in 'warnings'."""
    n = 0
    for w in warnings:
        if not isinstance(w, dict):
            continue
        for msg in w.get("warnings") or []:
            if "subcategor" in str(msg).lower() and (
                "null" in str(msg).lower() or "drop" in str(msg).lower()
            ):
                n += 1
    return n


# ===========================================================================
# BF-10 — the morning report: one ledger, both lanes, one reconciliation
# ===========================================================================
def build_report(store: Any, run_id: int | None = None, kind: str | None = None) -> dict[str, Any]:
    """Assemble the 09:00 artifact from `backfill_runs` + the live backlog.

    ⚠ ONE LEDGER, TWO LANES. `kind='label'` and `kind='push'` rows live in the
    same table precisely so the morning report reads ONE thing."""
    label = (
        store.get_backfill_run(run_id) if run_id is not None
        else store.latest_backfill_run(kind="label")
    )
    push = (
        None if run_id is not None else store.latest_backfill_run(kind="push")
    )
    if kind == "label":
        push = None
    if kind == "push":
        label, push = None, (
            store.get_backfill_run(run_id) if run_id is not None
            else store.latest_backfill_run(kind="push")
        )
    counts = store.subcategory_backlog_counts()
    total_swe = counts.get("total_swe", 0) or 0

    def _pct(numerator: int) -> float | None:
        return round(100.0 * numerator / total_swe, 2) if total_swe else None

    report: dict[str, Any] = {
        "generated_at": _now_iso(),
        "label": _label_block(label) if label else None,
        "push": _push_block(push, counts) if push else None,
        "backlog": counts,
        "reconciliation": {
            # the enricher's view
            "local_coverage_pct": _pct(
                (counts.get("labelled", 0) or 0) + (counts.get("empty", 0) or 0)
            ),
            # what JVN should be able to SEE
            "shipped_coverage_pct": _pct(counts.get("shipped", 0) or 0),
            "pending_push": counts.get("pending_push", 0),
            "identity": (
                "shipped - push_skipped_human - push_nulled_by_jvn == JVN's "
                "swe_subcategorized delta; pending_push is the ENTIRE legitimate "
                "gap. A difference LARGER than pending_push is a bug on one side."
            ),
        },
        "warnings": [],
    }
    behind = (
        "JVN is behind (the drain is in progress)"
        if counts.get("pending_push", 0) else "both sides agree"
    )
    report["reconciliation"]["which_side_is_behind"] = behind
    if push and (push.get("push_nulled_by_jvn") or 0) > 0:
        report["warnings"].append(
            f"⚠ push_nulled_by_jvn={push['push_nulled_by_jvn']} — the cross-repo "
            f"15-slug PARITY IS BROKEN. Run `cli parity-check` before pushing more."
        )
    return report


def _label_block(run: dict[str, Any]) -> dict[str, Any]:
    wall = _wall_seconds(run)
    model_rows = (run.get("model_labelled") or 0) + (run.get("empty_labelled") or 0)
    return {
        "run_id": run["id"],
        # ⚠ LOUDLY, AT THE TOP, when the run aborted.
        "status": run["status"],
        "aborted_reason": run.get("aborted_reason"),
        "labelled": {
            "rule_title": run.get("rule_labelled") or 0,
            "rule_tag": run.get("tag_labelled") or 0,
            "model": run.get("model_labelled") or 0,
            "empty": run.get("empty_labelled") or 0,
        },
        "selected": run.get("selected") or 0,
        "retired_at_cap": run.get("retired") or 0,
        "errors": {
            "transport": run.get("transport_errors") or 0,
            "parse": run.get("parse_errors") or 0,
            # ⚠ CALLED OUT SEPARATELY from parse errors: a non-zero echo-mismatch
            # means the BATCH SIZE is too high and the fix is a knob, not a rerun.
            # This is the counter that replaced positional repair; buried, the
            # replacement is inert.
            "echo_mismatch": run.get("echo_mismatch") or 0,
            "unanswered": run.get("unanswered") or 0,
        },
        "model_calls": run.get("model_calls") or 0,
        "wall_seconds": wall,
        # ⚠ so the NEXT night's length is predicted from LAST night rather than
        # from a 20-row probe
        "seconds_per_row": (
            round(wall / model_rows, 3) if wall and model_rows else None
        ),
        "taxonomy_version": run.get("taxonomy_version"),
        "rubric_version": run.get("rubric_version"),
        "notes": run.get("notes"),
    }


def _push_block(run: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    return {
        "run_id": run["id"],
        "status": run["status"],
        "aborted_reason": run.get("aborted_reason"),
        "pushed": run.get("pushed") or 0,
        "push_batches": run.get("push_batches") or 0,
        "push_rejected": run.get("push_rejected") or 0,
        "push_skipped_human": run.get("push_skipped_human") or 0,
        "push_nulled_by_jvn": run.get("push_nulled_by_jvn") or 0,
        "pool_pressure_events": run.get("pool_pressure_events") or 0,
        # ⚠ so an adaptive backoff that NEVER DECAYED is visible
        "effective_sleep_note": run.get("notes"),
        "pending_push": counts.get("pending_push", 0),
        "wall_seconds": _wall_seconds(run),
    }


def _wall_seconds(run: dict[str, Any]) -> float | None:
    from datetime import datetime

    started, ended = run.get("started_at"), run.get("ended_at")
    if not started or not ended:
        return None
    try:
        return round(
            (datetime.fromisoformat(ended) - datetime.fromisoformat(started))
            .total_seconds(), 3
        )
    except ValueError:
        return None


def render_report(report: dict[str, Any]) -> str:
    """The human form. ⚠ `aborted_reason` and `echo_mismatch` are the two lines
    an operator reads FIRST at 09:00."""
    lines: list[str] = []
    label, push = report.get("label"), report.get("push")
    if label and label.get("aborted_reason"):
        lines.append(
            f"⚠ LABEL RUN {label['run_id']} ABORTED: {label['aborted_reason']}"
        )
    if push and push.get("aborted_reason"):
        lines.append(
            f"⚠ PUSH RUN {push['run_id']} ABORTED: {push['aborted_reason']}"
        )
    for warning in report.get("warnings") or []:
        lines.append(warning)
    if label:
        lab = label["labelled"]
        lines.append(f"-- LABEL LANE (run {label['run_id']}, {label['status']}) --")
        lines.append(
            f"  labelled: rule/title={lab['rule_title']} rule/tag={lab['rule_tag']} "
            f"model={lab['model']} empty={lab['empty']}  selected={label['selected']}"
        )
        lines.append(f"  retired at the attempts cap: {label['retired_at_cap']}")
        err = label["errors"]
        lines.append(
            f"  errors: transport={err['transport']} parse={err['parse']}"
        )
        if err["echo_mismatch"]:
            lines.append(
                f"  ⚠ echo_mismatch={err['echo_mismatch']} — the batch size is "
                f"TOO HIGH. LOWER `--batch`; a rerun at the same size will not help."
            )
        else:
            lines.append("  echo_mismatch: 0")
        lines.append(f"  unanswered: {err['unanswered']}")
        lines.append(
            f"  model_calls={label['model_calls']} wall={label['wall_seconds']}s "
            f"seconds_per_row={label['seconds_per_row']}"
        )
    if push:
        lines.append(f"-- PUSH LANE (run {push['run_id']}, {push['status']}) --")
        lines.append(
            f"  pushed={push['pushed']} batches={push['push_batches']} "
            f"rejected={push['push_rejected']} "
            f"skipped_human={push['push_skipped_human']} "
            f"nulled_by_jvn={push['push_nulled_by_jvn']} "
            f"pool_pressure={push['pool_pressure_events']}"
        )
        lines.append(f"  {push['effective_sleep_note']}")
    rec = report["reconciliation"]
    lines.append("-- RECONCILIATION --")
    lines.append(
        f"  local_coverage={rec['local_coverage_pct']}%  "
        f"shipped_coverage={rec['shipped_coverage_pct']}%  "
        f"pending_push={rec['pending_push']}"
    )
    lines.append(f"  {rec['identity']}")
    lines.append(f"  -> {rec['which_side_is_behind']}")
    return "\n".join(lines)


def health_subcategory_block(store: Any) -> dict[str, Any]:
    """The `subcategory` key on `collect_health` — ⚠ `collect_health` is the ONE
    function feeding both `cli health` and the dashboard's `/api/health`, so this
    single edit surfaces both. Must not raise on a DB with no backfill run."""
    counts = store.subcategory_backlog_counts()
    total = counts.get("total_swe", 0) or 0

    def _pct(n: int) -> float | None:
        return round(100.0 * n / total, 2) if total else None

    label = store.latest_backfill_run(kind="label")
    push = store.latest_backfill_run(kind="push")
    return {
        "eligible": counts.get("eligible", 0),
        "labelled": counts.get("labelled", 0),
        "empty": counts.get("empty", 0),
        "stuck": counts.get("retired", 0),
        "total_swe": total,
        "local_coverage_pct": _pct(
            (counts.get("labelled", 0) or 0) + (counts.get("empty", 0) or 0)
        ),
        "shipped_coverage_pct": _pct(counts.get("shipped", 0) or 0),
        "pending_push": counts.get("pending_push", 0),
        "last_label_run": (
            {"id": label["id"], "status": label["status"],
             "ended_at": label.get("ended_at"),
             "aborted_reason": label.get("aborted_reason")}
            if label else None
        ),
        "last_push_run": (
            {"id": push["id"], "status": push["status"],
             "ended_at": push.get("ended_at"),
             "aborted_reason": push.get("aborted_reason")}
            if push else None
        ),
    }
