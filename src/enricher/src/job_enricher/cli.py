"""job-enricher CLI — the single supported interface the slash commands call.

Dispatch mirrors job-watcher: each subcommand stores its handler under
args.func. Return codes: 0 ok, 1 uncaught error, 2 bad usage, 75 lock held.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_enricher import enrich_config as ec
from job_enricher import lock as lock_mod
from job_enricher import taxonomy as tax
from job_enricher.clean import clean_description, truncate_for_agent
from job_enricher.eval.params import (
    PARAM_DRAW_SEED,
    PARAM_PRELABEL_ERROR_RATE,
    derive_audit_max,
)

UNMATCHED_WORKLIST_REL = "golden/review/unmatched-corrections.json"
from job_enricher.health import collect_health
from job_enricher.store import (
    JVN_ROOT,
    LAST_SCORECARD_HASH_KEY,
    REPO_ROOT,
    SCOPE_MAX_AGE_HOURS,
    ScopeUnavailableError,
    Store,
    now_iso,
)

logger = logging.getLogger(__name__)

# Confidence ceiling for a title-only classification (source captured no
# description). Kept below the default judge:confidence_ceiling (0.85) so these
# rows always route through the judge under the low_confidence scope.
TITLE_ONLY_MAX_CONFIDENCE = 0.5


def configure_logging() -> None:
    """Configure package logging once, at CLI entry.

    Logs to STDERR (stdout stays reserved for the JSON/command output the slash
    commands parse). Level comes from the LOG_LEVEL env var (default INFO).
    Idempotent — safe to call more than once. Handlers are attached to the
    package logger with propagate=False so records don't double-print via the
    root lastResort handler."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    pkg_logger = logging.getLogger("job_enricher")
    pkg_logger.setLevel(level)
    pkg_logger.propagate = False
    if not pkg_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        pkg_logger.addHandler(handler)


def _read_json_arg(args: argparse.Namespace) -> Any:
    """Read a JSON payload from --json, --json-file, or stdin."""
    if getattr(args, "json", None):
        return json.loads(args.json)
    if getattr(args, "json_file", None):
        with open(args.json_file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    data = sys.stdin.read()
    return json.loads(data) if data.strip() else []


# ---- lifecycle -------------------------------------------------------------
def _cmd_init(args: argparse.Namespace) -> int:
    Store().init_schema()
    print("init: schema ready")
    return 0


def _cmd_tick_acquire(args: argparse.Namespace) -> int:
    store = Store()
    lock_path = store.db_path.parent / ".tick.lock"
    acquired, reason = lock_mod.try_acquire(lock_path)
    if not acquired:
        print(f"tick-acquire: skipped — {reason}")
        return 75
    try:
        store.init_schema()
        tick_id = store.start_tick()
    except Exception:
        lock_mod.release(lock_path)
        raise
    print(f"tick-acquire: acquired tick_id={tick_id}")
    return 0


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    return int(raw) if raw and raw.isdigit() else None


def _cmd_tick_end(args: argparse.Namespace) -> int:
    """Close the current tick + release the lock.

    Stray-tick-end guard: when a tick id is supplied (`--tick-id` or the
    ENRICH_TICK_ID env var the wrapper exports), refuse to close anything if
    meta current_tick_id doesn't match — a stray tick-end from an overlapping
    invocation must never close the RUNNING tick or free its lock.

    Mass-nulling circuit breaker: a tick whose nulled-facet count exceeds 50%
    of classified rows (with classified >= 10) closes status='error' regardless
    of the requested status — that ratio means taxonomy drift, not per-row
    hallucinations."""
    from job_enricher import metrics as mx
    from job_enricher.metrics import (
        drift_suspected,
        subcategory_absent_drift,
        subcategory_empty_drift,
        window_counters,
    )

    store = Store()
    expected = args.tick_id if args.tick_id is not None else _env_int("ENRICH_TICK_ID")
    current = store.current_tick_id()
    if expected is not None and current != expected:
        print(
            f"tick-end: REFUSED — expected tick_id={expected} but current_tick_id="
            f"{current}; not closing another tick's state (stray tick-end guard)"
        )
        return 1

    status = args.status
    notes = args.notes
    if current is not None:
        tick = store.get_tick(current)
        if tick is not None and drift_suspected(tick):
            breaker = (
                f"mass-nulling circuit breaker: nulled_facets={tick['nulled_facets']} "
                f"of classified={tick['classified']} (>50%) — taxonomy drift suspected"
            )
            logger.error("tick-end: %s", breaker)
            status = "error"
            notes = f"{notes} | {breaker}" if notes else breaker

        # ⚠ BF-11: THE SECOND BREAKER BLOCK. Without this edit the two
        # subcategory flags ride in the /metrics payload but never trip the tick
        # status — the existing mass-nulling breaker works precisely because it
        # is wired HERE. A rolling window over the last SUBCAT_DRIFT_WINDOW_TICKS
        # ticks, INCLUDING the one being closed.
        window = window_counters(store)
        for fired, name, detail in (
            (
                subcategory_absent_drift(window),
                "subcategory_absent_drift",
                "the subcategories field never arrived (broken prompt, schema "
                "or engine)",
            ),
            (
                subcategory_empty_drift(window),
                "subcategory_empty_drift",
                "every evaluated SWE row answered [] (broken rubric) — ⚠ '[]' is "
                "TERMINAL, those rows have LEFT the backfill queue",
            ),
        ):
            if not fired:
                continue
            breaker = (
                f"{name}: over the last {mx.SUBCAT_DRIFT_WINDOW_TICKS} ticks "
                f"swe_classified={window['swe_classified']} "
                f"swe_subcat_evaluated={window['swe_subcat_evaluated']} "
                f"swe_subcategorized={window['swe_subcategorized']} — {detail}"
            )
            logger.error("tick-end: %s", breaker)
            status = "error"
            notes = f"{notes} | {breaker}" if notes else breaker

    tick_id = store.end_tick(status=status, notes=notes)
    lock_mod.release(
        store.db_path.parent / ".tick.lock",
        owner_pid=_env_int("ENRICH_LOCK_OWNER_PID"),
    )
    print(f"tick-end: closed tick_id={tick_id} status={status}")
    return 0


# ---- knobs -----------------------------------------------------------------
def _cmd_taxonomy_version(args: argparse.Namespace) -> int:
    # ⚠ Clear the lru_cache first: `_taxonomy_text` is lru_cache(maxsize=1), so a
    # same-process read after a SKILL.md edit would report the STALE rubric.
    from job_enricher.engines.prompts import reset_taxonomy_cache

    reset_taxonomy_cache()
    print(tax.taxonomy_version())
    return 0


def _cmd_enrich_config(args: argparse.Namespace) -> int:
    print(json.dumps(ec.config_snapshot(Store())))
    return 0


def _cmd_set_knob(args: argparse.Namespace) -> int:
    store = Store()
    result = args.setter(store, args.value)
    print(f"{args.knob}: {result}")
    return 0


def _cmd_reset_knob(args: argparse.Namespace) -> int:
    store = Store()
    ec.reset_knob(store, args.knob)
    print(f"{args.knob}: reset to committed default")
    return 0


# ---- pull ------------------------------------------------------------------
def _do_pull(store: Store, client: Any, limit: int | None) -> tuple[int, int, int]:
    """Pull from JVN then persist. The heartbeat is stamped ONLY after a
    successful pull (E6) so a failed pull can't mask a dead laptop with a fresh
    'alive' timestamp. Returns (inserted, skipped_unchanged, received)."""
    jobs = client.pull_pending(limit=limit)
    store.heartbeat()
    inserted, skipped = store.enqueue_inbox(jobs)
    store.bump_tick_counters(claimed=inserted)
    return inserted, skipped, len(jobs)


def _cmd_pull(args: argparse.Namespace) -> int:
    from job_enricher.jvn_client import JVNClient

    store = Store()
    store.init_schema()
    # Cap the claim to the per-tick classify budget for IN-PROCESS engines: pulling
    # more than the serial local engine can classify per tick only grows the local
    # backlog (inflow > outflow) and buries freshly-posted jobs behind it. Matching
    # inflow to outflow keeps the backlog flat (drains in lulls) and preserves JVN's
    # newest-first claim order. `claude-code` fan-out resolves to None (unbounded).
    engine = ec.get_classify_engine(store)
    cap = _resolve_per_tick_limit(store, engine, args.limit)
    inserted, skipped, received = _do_pull(store, JVNClient(), cap)
    print(f"pull: claimed={inserted} skipped_unchanged={skipped} received={received}")
    return 0


# ---- clean (Stage A, deterministic) ---------------------------------------
def _cmd_clean(args: argparse.Namespace) -> int:
    store = Store()
    started = now_iso()
    import time as _t

    t0 = _t.monotonic()
    rows = store.jobs_needing_clean(limit=args.limit)
    n = 0
    for row in rows:
        cleaned = clean_description(row["description_html"])
        store.record_clean(row["source_id"], row["job_listing_id"], cleaned)
        n += 1
    dur = int((_t.monotonic() - t0) * 1000)
    store.record_stage_timing("clean", started, now_iso(), dur, item_count=n)
    store.bump_tick_counters(cleaned=n)
    print(f"clean: cleaned={n}")
    return 0


# ---- chunk-file handoff (queue -> sub-agents) ------------------------------
# The queue commands write the full job payloads to per-chunk files under
# data/chunks/ and print only a SMALL manifest, so the orchestrator that fans
# out sub-agents never holds job text in its own context (at PULL_LIMIT=60 the
# old inline handoff put ~2x every clean description in the orchestrator
# transcript and risked mid-tick compaction). Each sub-agent Reads its own
# chunk file instead.
CHUNK_DIR_NAME = "chunks"


def _chunk_dir(store: Store) -> Path:
    return store.db_path.parent / CHUNK_DIR_NAME


def _clear_chunks(chunk_dir: Path, prefix: str) -> None:
    """Delete this queue's previous chunk files (stale-chunk hygiene). Each
    command only ever touches its OWN prefix (classify-*.json / judge-*.json),
    and the single-flight tick lock guarantees no concurrent tick is reading
    them, so unlinking is safe."""
    for stale in sorted(chunk_dir.glob(f"{prefix}-*.json")):
        stale.unlink(missing_ok=True)


def _write_queue_chunks(
    store: Store, rows: list[dict[str, Any]], prefix: str, batch_size: int
) -> list[dict[str, Any]]:
    """Chunk `rows` into files of `batch_size` jobs under data/chunks/ and
    return the manifest ``[{"chunk_file": <abs path>, "count": N}, ...]`` —
    no ids, titles, or descriptions ever appear in the manifest. Always clears
    the prefix's stale chunk files first, so an empty queue returns [] and
    leaves no files behind. Paths are absolute because the sub-agents' Read
    tool requires absolute paths."""
    chunk_dir = _chunk_dir(store)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    _clear_chunks(chunk_dir, prefix)
    if not rows:
        return []
    tick_id = store.current_tick_id()
    run_id = (
        f"t{tick_id}"
        if tick_id is not None
        else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    manifest: list[dict[str, Any]] = []
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        path = chunk_dir / f"{prefix}-{run_id}-{start // batch_size + 1:02d}.json"
        path.write_text(json.dumps(chunk), encoding="utf-8")
        manifest.append({"chunk_file": str(path.resolve()), "count": len(chunk)})
    return manifest


# ---- classify queue + record (Stage B) ------------------------------------
def _resolve_per_tick_limit(store: Store, engine: str, explicit: int | None) -> int | None:
    """Bound how many rows an IN-PROCESS engine (ollama/opencode) queues per tick.

    These engines run serially on one local GPU, so queueing the whole cleaned
    backlog would make `classify-run`/`judge-run` grind for hours and get killed by
    the wrapper's 3 h watchdog BEFORE write-back + tick-end ever run — the tick
    delivers nothing and never closes. Capping the queue to `enrich:per_tick_limit`
    makes every tick finish and write its slice back; the backlog drains over ticks.
    An explicit `--limit` still wins, and the `claude-code` parallel fan-out is left
    unbounded (it clears a batch fast)."""
    if explicit is not None:
        return explicit
    if engine == "claude-code":
        return None
    return ec.get_enrich_per_tick_limit(store)


def _cmd_classify_queue(args: argparse.Namespace) -> int:
    store = Store()
    engine = ec.get_classify_engine(store)
    limit = _resolve_per_tick_limit(store, engine, args.limit)
    rows = store.jobs_needing_classify(limit=limit)
    out = []
    for r in rows:
        out.append(
            {
                "job_listing_id": r["job_listing_id"],
                "source_id": r["source_id"],
                "title": r["title"],
                "company": r["company"],
                "raw_location": r["raw_location"],
                "clean_description": truncate_for_agent(r["clean_description"] or ""),
            }
        )
    batch = 1 if engine != "claude-code" else ec.get_classify_batch_size(store)
    manifest = _write_queue_chunks(store, out, "classify", batch)
    print(json.dumps(manifest))
    return 0


# ⚠ `_coerce_json_field` turns None into '[]'. That is correct for
# level_includes/tags/locations, where "absent" and "empty" mean the same thing —
# and it would DESTROY the subcategory tri-state on the very first write. Use
# `_coerce_subcategories_field` there, and do not "simplify" the two together.
def _coerce_json_field(value: Any) -> str:
    return json.dumps(value if value is not None else [])


# ⚠ THE SENTINEL. `item.get('subcategories')` cannot distinguish "the model
# omitted the field" from "the model emitted []" — and those are DIFFERENT
# STATES: absent means never evaluated (the row stays in the backfill queue),
# `[]` means evaluated and no specialty applies (TERMINAL, never re-queued).
# JSON cannot tell them apart after the fact, so the distinction has to be made
# at the boundary, here.
_MISSING = object()


def _coerce_subcategories_field(value: Any) -> str | None:
    """None stays NULL; a list is JSON-encoded.

    ⚠ NOT `_coerce_json_field` — that one does
    `json.dumps(value if value is not None else [])`, i.e. it turns None into
    '[]' and would collapse "never evaluated" into "evaluated, none apply" on
    every single classify write, silently draining the backfill queue before it
    ever filled."""
    if value is None:
        return None
    return json.dumps(value)


def _coerce_confidence(value: Any) -> float | None:
    """Best-effort numeric confidence. A local model can emit a string
    ("0.5"/"medium"), a dict of per-facet scores, or other junk where a float
    belongs; anything non-numeric becomes None — which the judge-scope routing
    and needs_human floor already treat as "unsure" — instead of raising at a
    comparison or the sqlite bind. Bools are junk here, not numbers."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _subcategory_confidence(subcats: Any, raw: Any) -> float | None:
    """⚠ SHARED CONTRACT 1.2 A: `subcategory_confidence` MUST be null when
    `subcategories` is `[]` or null.

    A confidence with no label behind it is a contradiction on the wire, and it
    is a SILENT one: the row still persists, still ships, still counts as
    written. Downstream it poisons subcategory-confidence calibration, which
    would then be measured over rows carrying no subcategory at all. The rule is
    enforced HERE rather than trusted from the model, because the model is
    exactly what emits the contradiction (an item with `subcategories` absent
    and `subcategory_confidence: 0.7` is a real observed shape).

    Anything that is not a NON-EMPTY list — None, `[]`, or model junk such as a
    dict or a bare string — zeroes the confidence to None."""
    if not isinstance(subcats, list) or not subcats:
        return None
    return _coerce_confidence(raw)


def _coerce_text_field(value: Any) -> str | None:
    """Free-text column (reasoning/notes): strings pass through; structured
    junk is JSON-encoded so the content stays inspectable instead of crashing
    the bind."""
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _coerce_int_field(value: Any) -> int | None:
    """Integer column (latency ms): numeric -> int, junk -> None, never raises."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nonempty(value: Any) -> bool:
    return bool(value) and bool(str(value).strip())


def _record_llm_stage_timing(store: Store, stage: str, items: int) -> None:
    """Attribute wall time to an LLM stage (classify/judge) at record time: the
    stage window runs from the current tick's previous stage event (or the tick
    start) to now. No-ops outside a tick — record_stage_timing needs one."""
    ended = now_iso()
    started = store.last_stage_event_at() or ended
    try:
        dur_ms = int(
            (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds()
            * 1000
        )
    except ValueError:
        dur_ms = 0
    store.record_stage_timing(stage, started, ended, max(dur_ms, 0), item_count=items)


def record_enrichment_items(
    store: Store, items: list[dict[str, Any]], version: str,
    classify_model: str | None = None,
) -> dict[str, int]:
    """Validate + persist classify results. Returns a counts dict:
    ``{"recorded", "needs_human", "title_only", "skipped", "skipped_unknown",
    "nulled_facets"}``.

    Rows with an empty job_listing_id are skipped (E10). The composite identity
    guard: an item must resolve to a CLAIMED (source_id, job_listing_id) inbox
    pair — a hallucinated/typo'd job_listing_id or an echoed source_id that
    doesn't match any inbox row is skipped + warned + counted as
    ``skipped_unknown`` instead of aborting the whole wave with an FK
    IntegrityError (the 'never raises' contract). An item without a source_id
    is resolved from the inbox only when the bare id maps to exactly ONE
    source. Rows with a category/level outside the canonical taxonomy get the
    bad slug nulled (counted in ``nulled_facets``) and are flagged needs_human
    so the hallucination is caught locally instead of shipped to JVN (E4).
    Scalar fields from the engine are type-coerced before the bind — a
    non-numeric confidence becomes None (judge-routed), structured
    reasoning is JSON-encoded, junk latency becomes None — so a malformed
    model response can never abort the wave at the sqlite layer.
    Never raises on bad data."""
    item_ids = [
        i.get("job_listing_id")
        for i in items
        if isinstance(i, dict) and i.get("job_listing_id")
    ]
    sources_by_id = store.inbox_sources_by_id(item_ids)
    # Rows whose source captured no description -> classified from title alone.
    # Marked title_only + confidence-clamped at record time so the low-signal
    # label is a code-level guarantee (routes through the judge under the
    # low_confidence scope), not dependent on the classify agent complying.
    title_only_pairs = store.empty_clean_description_pairs(item_ids)
    recorded = 0
    needs_human_n = 0
    title_only_n = 0
    skipped = 0
    skipped_unknown = 0
    nulled = 0
    subcategory_recorded = 0
    subcategory_missing = 0
    subcategory_empty = 0
    subcategory_truncated = 0
    swe_classified = 0
    swe_subcat_evaluated = 0
    swe_subcategorized = 0
    for item in items:
        jid = item.get("job_listing_id")
        if not _nonempty(jid):
            skipped += 1
            logger.warning("record-enrichment: skipping item with empty job_listing_id")
            continue
        claimed_sources = sources_by_id.get(jid, [])
        source_id = item.get("source_id")
        if _nonempty(source_id):
            if source_id not in claimed_sources:
                skipped_unknown += 1
                logger.warning(
                    "record-enrichment: (source_id=%r, job_listing_id=%r) matches no "
                    "claimed inbox row (hallucinated id or wrong source echoed); "
                    "skipping item instead of raising", source_id, jid,
                )
                continue
        elif len(claimed_sources) == 1:
            source_id = claimed_sources[0]
        else:
            skipped_unknown += 1
            logger.warning(
                "record-enrichment: job_listing_id=%r has no usable source_id "
                "(%d inbox row(s) claim that id); skipping item",
                jid, len(claimed_sources),
            )
            continue
        category, level, bad = tax.validate_facets(item.get("category"), item.get("level"))
        # ⚠ THE ABSENT-VS-EMPTY LINE. Under D3 this matters MORE, not less: the
        # classify lane now works from the compact section 1b, so "the model said
        # nothing" is both more common and more meaningful.
        raw_subcats = item.get("subcategories", _MISSING)
        subcats, sub_bad, sub_warnings = tax.validate_subcategories(
            category, None if raw_subcats is _MISSING else raw_subcats
        )
        bad = bad + sub_bad
        needs_human = False
        if bad:
            needs_human = True
            nulled += 1
            for facet, value in bad:
                logger.warning(
                    "record-enrichment: job_listing_id=%s has invalid %s=%r (not in taxonomy); "
                    "nulled + flagged needs_human", jid, facet, value,
                )
        # ⚠ A warning is a RULE APPLICATION (truncation, a full_stack
        # suppression), not a hallucination — it must NEVER set needs_human.
        for warning in sub_warnings:
            logger.info(
                "record-enrichment: job_listing_id=%s subcategory rule applied: %s",
                jid, warning,
            )
        subcategory_truncated += len(sub_warnings)
        title_only = (source_id, jid) in title_only_pairs
        # Coerced on EVERY path, not just title-only: a raw non-scalar (qwen
        # once returned a dict of per-facet scores) crashes the sqlite bind and
        # kills the whole classify-run. None routes the row to the judge.
        confidence = _coerce_confidence(item.get("confidence"))
        if title_only:
            # Reduced-signal label (title only): clamp below the judge ceiling
            # so it is always re-checked, whatever the agent claimed.
            conf_num = confidence if confidence is not None else TITLE_ONLY_MAX_CONFIDENCE
            confidence = min(conf_num, TITLE_ONLY_MAX_CONFIDENCE)
        store.record_enrichment(
            {
                "job_listing_id": jid,
                "source_id": source_id,
                "category": category,
                "level": level,
                "level_includes": _coerce_json_field(item.get("level_includes")),
                "tags": _coerce_json_field(item.get("tags")),
                "locations": _coerce_json_field(item.get("locations")),
                "classify_confidence": confidence,
                "classify_reasoning": _coerce_text_field(item.get("reasoning")),
                "classify_latency_ms": _coerce_int_field(item.get("classify_latency_ms")),
                "taxonomy_version": version,
                "needs_human": needs_human,
                "title_only": title_only,
                "classify_model": classify_model,
                "subcategories": _coerce_subcategories_field(subcats),
                # ⚠ Keyed off `subcats`, NOT off the raw item: contract 1.2 A
                # forbids a confidence when the array is [] or null, and the
                # model routinely sends one anyway.
                "subcategory_confidence": _subcategory_confidence(
                    subcats, item.get("subcategory_confidence")
                ),
                # ⚠ Source stays None when subcats is None: a NEVER-EVALUATED row
                # must not be stamped with a provenance it never had, or the
                # backfill lane cannot tell it apart from a real classify answer.
                "subcategory_source": None if subcats is None else "classify",
            }
        )
        recorded += 1
        needs_human_n += 1 if needs_human else 0
        title_only_n += 1 if title_only else 0
        if category == tax.SUBCATEGORY_PARENT:
            swe_classified += 1
        if subcats is None:
            # Absent on an SWE row = the backfill-eligible count.
            if category == tax.SUBCATEGORY_PARENT:
                subcategory_missing += 1
        else:
            subcategory_recorded += 1
            if category == tax.SUBCATEGORY_PARENT:
                swe_subcat_evaluated += 1        # NON-NULL, INCLUDING []
            if subcats:
                if category == tax.SUBCATEGORY_PARENT:
                    swe_subcategorized += 1
            else:
                subcategory_empty += 1
    # ⚠ ALL THREE tick counters are bumped here. `bump_tick_counters` filters its
    # kwargs against `TICK_COUNTER_COLS` and SILENTLY DROPS unlisted keys — all
    # three are in that frozenset via ENR-ST-1, and without these bumps BF-11's
    # two breakers read 0 forever while looking perfectly healthy.
    if swe_classified or swe_subcat_evaluated or swe_subcategorized:
        store.bump_tick_counters(
            swe_classified=swe_classified,
            swe_subcat_evaluated=swe_subcat_evaluated,
            swe_subcategorized=swe_subcategorized,
        )
    return {
        "recorded": recorded,
        "needs_human": needs_human_n,
        "title_only": title_only_n,
        "skipped": skipped,
        "skipped_unknown": skipped_unknown,
        "nulled_facets": nulled,
        "subcategory_recorded": subcategory_recorded,
        "subcategory_missing": subcategory_missing,
        "subcategory_empty": subcategory_empty,
        "subcategory_truncated": subcategory_truncated,
    }


def _cmd_record_enrichment(args: argparse.Namespace) -> int:
    store = Store()
    payload = _read_json_arg(args)
    items = payload if isinstance(payload, list) else [payload]
    version = tax.taxonomy_version()
    res = record_enrichment_items(
        store, items, version, classify_model=ec.get_classify_model(store)
    )
    store.bump_tick_counters(
        classified=res["recorded"], needs_human=res["needs_human"],
        nulled_facets=res["nulled_facets"],
    )
    _record_llm_stage_timing(store, "classify", res["recorded"])
    print(
        f"record-enrichment: recorded={res['recorded']} needs_human={res['needs_human']} "
        f"title_only={res['title_only']} "
        f"skipped={res['skipped']} skipped_unknown={res['skipped_unknown']} "
        f"nulled_facets={res['nulled_facets']} "
        f"subcategory_recorded={res['subcategory_recorded']} "
        f"subcategory_missing={res['subcategory_missing']} "
        f"subcategory_empty={res['subcategory_empty']} "
        f"subcategory_truncated={res['subcategory_truncated']}"
    )
    return 0


# ---- judge queue + record (Stage C) ---------------------------------------
def _needs_judge(e: Any, ceiling: float) -> bool:
    """scope=low_confidence routing: judge only the rows where judging has a
    measurable payoff — classify was unsure (confidence below the ceiling, or
    missing), a facet was nulled at ingest (invalid slug), or the row is
    already flagged needs_human. Confident rows ship as-is: the measured lift
    of judging them was negative (level churn away from gold).

    ⚠ EXPLICITLY NO SUBCATEGORY CLAUSE HERE, and there must never be one.
    Roughly half the corpus is `software_engineering`, so a
    `SWE and subcategories IS NULL` condition would route half of it to the
    judge and blow up judge volume on a lane already at capacity. NULL
    subcategories are the BACKFILL lane's queue, not the judge's. A standing
    regression test in tests/test_cli.py pins this."""
    conf = e["classify_confidence"]
    if conf is None or conf < ceiling:
        return True
    if e["needs_human"]:
        return True
    if e["category"] is None or e["level"] is None:
        return True
    return False


def _cmd_judge_queue(args: argparse.Namespace) -> int:
    store = Store()
    if not ec.get_judge_enabled(store):
        # still clear stale judge chunk files so a disabled judge leaves
        # nothing behind for a later tick to pick up
        _write_queue_chunks(store, [], "judge", 1)
        print("[]")
        return 0
    scope = ec.get_judge_scope(store)
    ceiling = ec.get_judge_confidence_ceiling(store)
    engine = ec.get_judge_engine(store)
    # Cap AFTER the scope filter, not via a SQL LIMIT: under scope=low_confidence,
    # already-sent high-confidence rows stay judged=0 forever (scope never judges
    # them) and pile up at the front of enriched_unjudged. A pre-filter LIMIT would
    # let that backlog starve the actual low-confidence work; filtering first, then
    # truncating, always yields up to `limit` genuinely judge-eligible rows.
    limit = _resolve_per_tick_limit(store, engine, args.limit)
    enr = store.enriched_unjudged()
    out = []
    for e in enr:
        if scope == "low_confidence" and not _needs_judge(e, ceiling):
            continue
        out.append(
            {
                "job_listing_id": e["job_listing_id"],
                "source_id": e["source_id"],
                "title": e["title"] or "",
                "company": e["company"] or "",
                "raw_location": e["raw_location"],
                "clean_description": truncate_for_agent(e["clean_description"] or ""),
                "current": {
                    "category": e["category"],
                    "level": e["level"],
                    # ⚠ PROD/EVAL PARITY. The eval judge queue (_cmd_eval_run)
                    # puts `subcategories` in `current`, and build_judge_prompt
                    # invites a correction on it. Omitting it here would have the
                    # judge RE-DERIVE the facet from the description in prod while
                    # VERIFYING it in eval: _merge_judge's rails would be gating a
                    # blind guess, and the judge-correction rate ENR-CLS-3 measures
                    # would not be the one prod produces. None (never evaluated)
                    # survives as None — the prompt's "leave it alone" case.
                    "subcategories": (
                        None if e["subcategories"] is None
                        else json.loads(e["subcategories"])
                    ),
                    "level_includes": json.loads(e["level_includes"] or "[]"),
                    "tags": json.loads(e["tags"] or "[]"),
                    "locations": json.loads(e["locations"] or "[]"),
                    "confidence": e["classify_confidence"],
                },
            }
        )
        if limit is not None and len(out) >= limit:
            break
    batch = 1 if engine != "claude-code" else ec.get_classify_batch_size(store)
    manifest = _write_queue_chunks(store, out, "judge", batch)
    print(json.dumps(manifest))
    return 0


def apply_judge_verdicts(
    store: Store, items: list[dict[str, Any]], floor: float,
    judge_model: str | None = None,
) -> dict[str, int]:
    """Merge + persist judge verdicts. Returns a counts dict:
    ``{"judged", "corrected", "needs_human", "skipped", "rejected_corrections"}``.

    Verdicts are matched to their enrichment row by the composite
    (source_id, job_listing_id) pair; a verdict without a source_id resolves
    by bare id only when unambiguous. A verdict with no matching row is COUNTED
    as skipped and warned rather than silently dropped (E13)."""
    existing = _enrichment_map(
        store, [i.get("job_listing_id") for i in items if isinstance(i, dict) and i.get("job_listing_id")]
    )
    by_id: dict[str, list[dict[str, Any]]] = {}
    for (_, jid), row in existing.items():
        by_id.setdefault(jid, []).append(row)
    # Read the knob ONCE per run, not per row.
    subcategory_corrections = ec.get_judge_subcategory_corrections(store)
    judged = 0
    corrected = 0
    needs_human = 0
    skipped = 0
    rejected_corrections = 0
    for item in items:
        jid = item.get("job_listing_id")
        sid = item.get("source_id")
        base: dict[str, Any] | None = None
        if jid:
            if sid:
                base = existing.get((sid, jid))
            else:
                candidates = by_id.get(jid, [])
                if len(candidates) == 1:
                    base = candidates[0]
                elif len(candidates) > 1:
                    logger.warning(
                        "record-judge: verdict for job_listing_id=%r has no source_id "
                        "and %d rows share that id — skipping (ambiguous)",
                        jid, len(candidates),
                    )
        if base is None:
            skipped += 1
            logger.warning(
                "record-judge: skipping verdict for unknown (source_id=%r, "
                "job_listing_id=%r) (no enrichment row)", sid, jid,
            )
            continue
        merged = _merge_judge(
            base, item, floor, subcategory_corrections=subcategory_corrections
        )
        rejected_corrections += merged.pop("rejected_corrections", 0)
        merged["judge_model"] = judge_model
        store.record_judge(merged)
        judged += 1
        corrected += 0 if merged["judge_pass"] else 1
        needs_human += 1 if merged["needs_human"] else 0
    return {
        "judged": judged,
        "corrected": corrected,
        "needs_human": needs_human,
        "skipped": skipped,
        "rejected_corrections": rejected_corrections,
    }


def _cmd_record_judge(args: argparse.Namespace) -> int:
    store = Store()
    payload = _read_json_arg(args)
    items = payload if isinstance(payload, list) else [payload]
    floor = ec.get_judge_human_floor(store)
    res = apply_judge_verdicts(
        store, items, floor, judge_model=ec.get_judge_model(store)
    )
    store.bump_tick_counters(
        judged=res["judged"], corrected=res["corrected"], needs_human=res["needs_human"]
    )
    _record_llm_stage_timing(store, "judge", res["judged"])
    print(
        f"record-judge: judged={res['judged']} corrected={res['corrected']} "
        f"needs_human={res['needs_human']} skipped={res['skipped']} "
        f"rejected_corrections={res['rejected_corrections']}"
    )
    return 0


# ---- engine-driven classify/judge (Python inference path) ------------------
# When classify:engine / judge:engine is not 'claude-code', /enrich-tick runs
# these INSTEAD of the sandboxed Claude sub-agent fan-out: same chunk files, same
# recorder contract (so validation, level rails, provenance, durability are all
# reused), but inference happens in-process via the engines/ package.
def _stage_engine_model(
    store: Store, stage: str, engine_override: str | None = None,
    model_override: str | None = None,
) -> tuple[str, str]:
    """Resolve (engine_kind, model) for a stage. `model` is the Claude tier for
    the claude-code engine, else the Ollama tag (opencode:model). Overrides win
    (used by eval-run to pin an explicit tier/tag)."""
    if stage == "classify":
        engine_kind = engine_override or ec.get_classify_engine(store)
        claude_model = ec.get_classify_model(store)
    else:
        engine_kind = engine_override or ec.get_judge_engine(store)
        claude_model = ec.get_judge_model(store)
    if engine_kind == "claude-code":
        return engine_kind, (model_override or claude_model)
    return engine_kind, (model_override or ec.get_opencode_model(store))


def _resolve_chunk_files(store: Store, prefix: str, chunk_file: str | None) -> list[str]:
    if chunk_file:
        return [chunk_file]
    return [str(p) for p in sorted(_chunk_dir(store).glob(f"{prefix}-*.json"))]


def _cmd_classify_run(args: argparse.Namespace) -> int:
    from job_enricher.engines import EngineError, build_engine

    store = Store()
    engine_kind, model = _stage_engine_model(store, "classify", args.engine)
    engine = build_engine(engine_kind, model=model)
    version = tax.taxonomy_version()
    chunk_files = _resolve_chunk_files(store, "classify", args.chunk_file)
    totals = {
        "recorded": 0, "needs_human": 0, "title_only": 0,
        "skipped": 0, "skipped_unknown": 0, "nulled_facets": 0,
    }
    abandoned = 0
    unreadable_chunks = 0
    newly_failed = 0
    for cf in chunk_files:
        try:
            jobs = json.loads(Path(cf).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # ⚠ SAME FAILURE MODE THE ENGINE HANDLER SIX LINES BELOW EXISTS TO
            # KILL. This `continue` used to leave `errors` at 0, so a whole lost
            # chunk closed the tick `status=ok errors=0` — the loss was visible
            # only in a log nobody reads.
            #
            # ⚠ NO `record_classify_failure` HERE, DELIBERATELY: the chunk's
            # identity list is exactly what was lost, so there are no
            # (source_id, job_listing_id) pairs to bump `inbox.attempts` on, and
            # bumping every `cleaned` row instead would fail rows this chunk never
            # held. The rows stay `cleaned` and are re-queued next tick, which is
            # the right retry — `classify-queue` clears and rewrites the prefix
            # every tick, so a corrupt file cannot be re-read forever.
            logger.error("classify-run: unreadable chunk %s: %s", cf, exc)
            unreadable_chunks += 1
            continue
        try:
            items = engine.classify(jobs)
        except EngineError as exc:
            # P0-3: an abandoned chunk is NO LONGER SILENT. Before this, the
            # `continue` left `errors` at 0 and `inbox.attempts` untouched, so
            # the tick closed status=ok while losing the whole chunk — and the
            # same rows were re-claimed and re-abandoned every tick forever.
            logger.error("classify-run: %s failed on %s: %s", engine.name, cf, exc)
            abandoned += len(jobs)
            pairs = [
                (j.get("source_id"), j.get("job_listing_id"))
                for j in jobs
                if j.get("source_id") and j.get("job_listing_id")
            ]
            newly_failed += len(store.record_classify_failure(pairs))
            continue
        res = record_enrichment_items(store, items, version, classify_model=model)
        for k in totals:
            totals[k] += res.get(k, 0)
    store.bump_tick_counters(
        classified=totals["recorded"], needs_human=totals["needs_human"],
        nulled_facets=totals["nulled_facets"],
        # `abandoned` counts JOBS (the engine handler knows the chunk's contents);
        # an unreadable chunk counts as ONE error because its job count is
        # precisely what could not be read. Both are real errors either way.
        errors=abandoned + unreadable_chunks,
    )
    _record_llm_stage_timing(store, "classify", totals["recorded"])
    print(
        f"classify-run: engine={engine_kind} model={model} "
        f"recorded={totals['recorded']} needs_human={totals['needs_human']} "
        f"abandoned={abandoned} newly_failed={newly_failed} "
        f"unreadable_chunks={unreadable_chunks} "
        f"title_only={totals['title_only']} "
        f"skipped={totals['skipped']} skipped_unknown={totals['skipped_unknown']} "
        f"nulled_facets={totals['nulled_facets']} chunks={len(chunk_files)}"
    )
    return 0


def _cmd_judge_run(args: argparse.Namespace) -> int:
    from job_enricher.engines import EngineError, build_engine

    store = Store()
    engine_kind, model = _stage_engine_model(store, "judge", args.engine)
    engine = build_engine(engine_kind, model=model)
    floor = ec.get_judge_human_floor(store)
    chunk_files = _resolve_chunk_files(store, "judge", args.chunk_file)
    totals = {"judged": 0, "corrected": 0, "needs_human": 0, "skipped": 0, "rejected_corrections": 0}
    # ⚠ A LOST JUDGE CHUNK IS AN ERROR, NOT A NO-OP. Both `continue`s below used
    # to leave the tick at `errors=0`, so a whole chunk vanishing looked exactly
    # like "there was nothing to judge". Unlike classify there is no un-fail path
    # to run: the rows keep their classify verdict and simply stay unjudged, so
    # visibility IS the whole fix.
    lost_chunks = 0
    for cf in chunk_files:
        try:
            items = json.loads(Path(cf).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("judge-run: unreadable chunk %s: %s", cf, exc)
            lost_chunks += 1
            continue
        try:
            verdicts = engine.judge(items)
        except EngineError as exc:
            logger.error("judge-run: %s failed on %s: %s", engine.name, cf, exc)
            lost_chunks += 1
            continue
        res = apply_judge_verdicts(store, verdicts, floor, judge_model=model)
        for k in totals:
            totals[k] += res.get(k, 0)
    store.bump_tick_counters(
        judged=totals["judged"], corrected=totals["corrected"],
        needs_human=totals["needs_human"], errors=lost_chunks,
    )
    _record_llm_stage_timing(store, "judge", totals["judged"])
    print(
        f"judge-run: engine={engine_kind} model={model} judged={totals['judged']} "
        f"corrected={totals['corrected']} needs_human={totals['needs_human']} "
        f"skipped={totals['skipped']} rejected_corrections={totals['rejected_corrections']} "
        f"lost_chunks={lost_chunks} chunks={len(chunk_files)}"
    )
    return 0


# ---- eval-run (headless per-engine prediction generator) -------------------
def _eval_classify_pred(item: dict[str, Any], clean_desc: str) -> dict[str, Any]:
    """A classify prediction row (the judge-off artifact).

    ⚠ THIS IS A HAND-WRITTEN KEY LIST. A field absent from it is silently absent
    from every eval artifact, and every metric over that field reads 0.0 with no
    error anywhere. Under D3 this is the ONLY channel that can tell you whether
    the compact section 1b is good enough, so subcategories cannot be an
    afterthought here."""
    return {
        "job_listing_id": item.get("job_listing_id"),
        "source_id": item.get("source_id"),
        "category": item.get("category"),
        # ⚠ PRESERVE None. `or []` would destroy the distinction between "the
        # model omitted it" and "the model said none apply" — and that
        # distinction IS a metric: it is the direct readout on whether the
        # compact rubric is being SEEN at all.
        "subcategories": item.get("subcategories"),
        # ⚠ Contract 1.2 A holds on the eval artifacts too, or subcategory
        # confidence is calibrated over rows carrying no label.
        "subcategory_confidence": _subcategory_confidence(
            item.get("subcategories"), item.get("subcategory_confidence")
        ),
        "level": item.get("level"),
        "level_includes": item.get("level_includes") or [],
        "tags": item.get("tags") or [],
        "locations": item.get("locations") or [],
        "confidence": item.get("confidence"),
        "reasoning": item.get("reasoning"),
        "classify_latency_ms": item.get("classify_latency_ms"),
        "clean_description": clean_desc,
    }


def _eval_post_judge_pred(cp: dict[str, Any], verdict: dict[str, Any], floor: float) -> dict[str, Any]:
    """Apply a judge verdict to a classify prediction via the SAME code-enforced
    rails as production (`_merge_judge`), then flatten to a judged prediction row."""
    base = {
        "job_listing_id": cp["job_listing_id"],
        "source_id": cp.get("source_id"),
        "category": cp.get("category"),
        "level": cp.get("level"),
        "level_includes": json.dumps(cp.get("level_includes") or []),
        "tags": json.dumps(cp.get("tags") or []),
        "locations": json.dumps(cp.get("locations") or []),
        # ⚠ _coerce_subcategories_field, NOT _coerce_json_field: the latter turns
        # None into '[]' and would make every unevaluated eval row look evaluated.
        "subcategories": _coerce_subcategories_field(cp.get("subcategories")),
        # ⚠ The classify confidence rides IN so `_merge_judge` can apply the same
        # rule production now applies: keep it when the judge leaves the label
        # alone, clear it when the judge moves the label (the number was measured
        # against a label the row no longer carries). Without this key the eval
        # artifact and the prod column would disagree on exactly the rows the
        # judge corrected — the rows the artifact exists to measure.
        "subcategory_confidence": cp.get("subcategory_confidence"),
        "needs_human": False,
    }
    merged = _merge_judge(base, verdict, floor)
    merged_subcats = (
        None if merged["subcategories"] is None
        else json.loads(merged["subcategories"])
    )
    return {
        "job_listing_id": cp["job_listing_id"],
        "source_id": cp.get("source_id"),
        "category": merged["category"],
        # ⚠ None survives as None on the way OUT too.
        "subcategories": merged_subcats,
        # ⚠ THE MERGE'S OWN ANSWER, not a re-derivation from the classify value.
        # `_merge_judge` already applied contract 1.2 A (null when the array is
        # `[]`/null) AND cleared a confidence the judge invalidated by moving the
        # label, so taking it from there is what keeps this artifact identical to
        # the column production stores.
        "subcategory_confidence": merged["subcategory_confidence"],
        "level": merged["level"],
        "level_includes": json.loads(merged["level_includes"]),
        "tags": json.loads(merged["tags"]),
        "locations": json.loads(merged["locations"]),
        "confidence": cp.get("confidence"),
        "reasoning": cp.get("reasoning"),
        "classify_latency_ms": cp.get("classify_latency_ms"),
        "judge_pass": bool(merged["judge_pass"]),
        "judge_reasoning": merged.get("judge_reasoning") or merged.get("judge_notes"),
        "judge_latency_ms": merged.get("judge_latency_ms"),
        "clean_description": cp.get("clean_description"),
    }


def _cmd_eval_run(args: argparse.Namespace) -> int:
    """Generate per-engine golden predictions headlessly (classify [+ judge]),
    with per-item latency + reasoning, for `cli eval --engine <e>` to score.
    Trusted golden text, so both open and Claude engines run in-process (unlike
    production, where Claude keeps the sandboxed sub-agent path)."""
    from job_enricher import clean
    from job_enricher.engines import EngineError, build_engine
    from job_enricher.engines.prompts import reset_taxonomy_cache

    # ⚠ A v6-vs-v7 A/B run in ONE process would otherwise score the first arm's
    # rubric TWICE and report a delta of zero — `_taxonomy_text` is
    # lru_cache(maxsize=1).
    reset_taxonomy_cache()
    from job_enricher.eval.golden import load_seed
    from job_enricher.eval.report import _predictions_path

    store = Store()
    engine_kind = args.engine
    is_claude = engine_kind == "claude-code"
    classify_model = args.classify_model or (
        ec.get_classify_model(store) if is_claude else ec.get_opencode_model(store)
    )
    judge_model = args.judge_model or (
        ec.get_judge_model(store) if is_claude else ec.get_opencode_model(store)
    )
    floor = ec.get_judge_human_floor(store)

    rows = load_seed()
    if args.human_only:
        rows = [r for r in rows if r.get("label_source") == "human"]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        which = "human-labeled " if args.human_only else ""
        print(f"eval-run: no {which}golden rows — run `cli build-golden-set`/`golden-merge` first.",
              file=sys.stderr)
        return 1
    batch = max(1, args.batch)
    do_judge = args.judge != "off"

    if getattr(args, "prompt", "classify") == "backfill":
        return _eval_run_backfill_lane(rows, engine_kind, classify_model, batch,
                                       getattr(args, "tag", None))

    jobs: list[dict[str, Any]] = []
    clean_by_key: dict[tuple[str, str], str] = {}
    for r in rows:
        # prefer an already-cleaned description (prod exports carry clean_description);
        # otherwise clean the raw HTML the same way the pipeline does.
        raw = r.get("clean_description") or clean.clean_description(r.get("description_html"))
        cd = clean.truncate_for_agent(raw or "")
        key = (r["source_id"], r["job_listing_id"])
        clean_by_key[key] = cd
        jobs.append({
            "job_listing_id": r["job_listing_id"], "source_id": r["source_id"],
            "title": r.get("title"), "company": r.get("company"),
            "raw_location": r.get("raw_location"), "clean_description": cd,
        })

    # ---- classify ----
    classify_engine = build_engine(engine_kind, model=classify_model)
    classify_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    total = len(jobs)
    for i in range(0, total, batch):
        chunk = jobs[i : i + batch]
        try:
            items = classify_engine.classify(chunk)
        except EngineError as exc:
            logger.error("eval-run: classify chunk @%d failed: %s", i, exc)
            items = []
        for it in items:
            classify_by_key[(it.get("source_id"), it.get("job_listing_id"))] = it
        print(f"  classify {min(i + batch, total)}/{total} [{engine_kind}/{classify_model}]",
              file=sys.stderr)

    # count golden rows that actually got a prediction (keys are the known input
    # ids after positional stamping) — NOT len(classify_by_key), which at batch>1
    # could hold hallucinated/mis-echoed keys and misreport the drop count.
    covered = sum(
        1 for r in rows if (r["source_id"], r["job_listing_id"]) in classify_by_key
    )
    print(f"eval-run: classify coverage {covered}/{total} (drops={total - covered}) "
          f"[{engine_kind}]", file=sys.stderr)

    judge_off = [
        _eval_classify_pred(classify_by_key[k], clean_by_key[k])
        for k in (( r["source_id"], r["job_listing_id"]) for r in rows)
        if k in classify_by_key
    ]
    tag = getattr(args, "tag", None)
    off_path = _predictions_path("off", engine_kind, tag)
    off_path.parent.mkdir(parents=True, exist_ok=True)
    off_path.write_text(json.dumps(judge_off, indent=2), encoding="utf-8")
    print(f"eval-run: wrote {len(judge_off)} classify predictions -> {off_path.name}")

    if not do_judge:
        return 0

    # ---- judge ----
    judge_engine = build_engine(engine_kind, model=judge_model)
    judge_items: list[dict[str, Any]] = []
    for r in rows:
        k = (r["source_id"], r["job_listing_id"])
        it = classify_by_key.get(k)
        if it is None:
            continue
        cp = _eval_classify_pred(it, clean_by_key[k])
        judge_items.append({
            "job_listing_id": r["job_listing_id"], "source_id": r["source_id"],
            "title": r.get("title"), "company": r.get("company"),
            "raw_location": r.get("raw_location"), "clean_description": clean_by_key[k],
            "current": {
                "category": cp["category"], "level": cp["level"],
                # Absent-vs-null matters to the judge too: the prompt tells it an
                # ABSENT value means "not yet evaluated" and must be left alone.
                "subcategories": cp["subcategories"],
                "level_includes": cp["level_includes"], "tags": cp["tags"],
                "locations": cp["locations"], "confidence": cp["confidence"],
            },
        })
    verdict_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    jt = len(judge_items)
    for i in range(0, jt, batch):
        chunk = judge_items[i : i + batch]
        try:
            verdicts = judge_engine.judge(chunk)
        except EngineError as exc:
            logger.error("eval-run: judge chunk @%d failed: %s", i, exc)
            verdicts = []
        for v in verdicts:
            verdict_by_key[(v.get("source_id"), v.get("job_listing_id"))] = v
        print(f"  judge {min(i + batch, jt)}/{jt} [{engine_kind}/{judge_model}]", file=sys.stderr)

    judged: list[dict[str, Any]] = []
    for r in rows:
        k = (r["source_id"], r["job_listing_id"])
        it = classify_by_key.get(k)
        if it is None:
            continue
        cp = _eval_classify_pred(it, clean_by_key[k])
        verdict = verdict_by_key.get(k)
        if verdict is None:
            # judge dropped the row — carry the classify label through as a pass
            verdict = {"passed": True, "confidence": cp.get("confidence"), "corrections": {}}
        judged.append(_eval_post_judge_pred(cp, verdict, floor))
    on_path = _predictions_path(None, engine_kind, tag)
    on_path.write_text(json.dumps(judged, indent=2), encoding="utf-8")
    print(f"eval-run: wrote {len(judged)} judged predictions -> {on_path.name}")
    return 0


# ⚠ THE BACKFILL LANE IS A DIFFERENT TASK FROM THE CLASSIFY LANE, AND THE GATE
# AS DESIGNED MEASURES ONLY THE FIRST. The live classify path sees title +
# company + raw_location + the FULL cleaned description; the backfill path sees
# title + company tags ONLY — the injection-boundary decision, taken because
# claude_code.py's docstring reserves headless `claude -p` for trusted golden
# text and job descriptions are untrusted. Without this lane roughly 8k rows
# would ship on a prompt nothing ever measured.
_BACKFILL_ROW_FIELDS = ("job_listing_id", "source_id", "title", "company", "tags")


def _eval_run_backfill_lane(
    rows: list[dict[str, Any]], engine_kind: str, model: str, batch: int,
    tag: str | None,
) -> int:
    """Score the SUBCATEGORY-ONLY prompt the production backfill actually runs.

    ⚠ IT CALLS `ChunkEngine.subcategory()` / `build_subcategory_prompt` — the
    SAME code the production backfill uses — rather than a parallel eval-local
    implementation. A hand-rolled input mode here would measure a prompt
    production never runs, which is worse than not measuring it at all because
    it looks like evidence.

    ⚠ HONEST LIMITATION: company tags are ABSENT from the golden seed today
    (the seed's `tags` field is a GOLD LABEL produced by an earlier draft run,
    not company tags), so this lane is effectively TITLE-ONLY here and its
    score is therefore a LOWER BOUND on the backfill's real quality.
    """
    from job_enricher.engines import EngineError, build_engine
    from job_enricher.eval.report import _predictions_path

    engine = build_engine(engine_kind, model=model, lane="backfill")
    projected = [
        {
            "job_listing_id": r["job_listing_id"],
            "source_id": r["source_id"],
            "title": r.get("title"),
            "company": r.get("company"),
            # ⚠ NOT `r['tags']` — that is the gold label. Only a real
            # `company_tags` field may feed this lane, and there is not one yet.
            "tags": r.get("company_tags") or [],
        }
        for r in rows
    ]
    by_key: dict[tuple[Any, Any], dict[str, Any]] = {}
    total = len(projected)
    for i in range(0, total, batch):
        chunk = projected[i : i + batch]
        try:
            items = engine.subcategory(chunk)
        except EngineError as exc:
            logger.error("eval-run[backfill]: chunk @%d failed: %s", i, exc)
            items = []
        for it in items:
            by_key[(it.get("source_id"), it.get("job_listing_id"))] = it
        print(f"  subcategory {min(i + batch, total)}/{total} "
              f"[{engine_kind}/{model}]", file=sys.stderr)

    covered = sum(1 for r in rows if (r["source_id"], r["job_listing_id"]) in by_key)
    print(f"eval-run[backfill]: coverage {covered}/{total} "
          f"(drops={total - covered}) [{engine_kind}]", file=sys.stderr)

    preds = []
    for r in rows:
        it = by_key.get((r["source_id"], r["job_listing_id"]))
        if it is None:
            continue
        subs, _bad, _warn = tax.validate_subcategories(
            tax.SUBCATEGORY_PARENT, it.get("subcategories")
        )
        preds.append({
            "job_listing_id": r["job_listing_id"],
            "source_id": r["source_id"],
            # the lane decides a SUBCATEGORY only; the gold parent is echoed
            "category": r.get("category"),
            "subcategories": subs,
            "subcategory_confidence": _subcategory_confidence(
                subs, it.get("subcategory_confidence")
            ),
            "subcategory_latency_ms": it.get("subcategory_latency_ms"),
            # ⚠ EMPTY BY CONSTRUCTION — the projection has nowhere to put a
            # description, which is the injection boundary made structural.
            "clean_description": "",
        })
    path = _predictions_path("off", engine_kind, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preds, indent=2), encoding="utf-8")
    print(f"eval-run[backfill]: wrote {len(preds)} subcategory predictions "
          f"-> {path.name}")
    return 0


# the judge may only change level (outside the new_grad/entry equivalence)
# when its OWN confidence clears this bar — enforced in code, not just prompt
JUDGE_LEVEL_CONFIDENCE_MIN = 0.8
# Same bar for a subcategory correction. In this codebase's own words
# (judge.md:52-53): "a rail the system doesn't enforce isn't a rail."
JUDGE_SUBCATEGORY_CONFIDENCE_MIN = 0.8
_LEVEL_EQUIVALENCE = frozenset({"new_grad", "entry"})


def _merge_judge(
    base: dict[str, Any],
    verdict: dict[str, Any],
    floor: float,
    *,
    subcategory_corrections: bool = True,
) -> dict[str, Any]:
    """Apply a judge verdict in place: keep existing facets unless the judge
    supplied a correction; stamp judge fields; flag needs_human below the floor.
    A judge-supplied category/level outside the canonical taxonomy is nulled and
    flags needs_human (E4) so a hallucinated correction is never shipped.

    Level-change rails (code-enforced — the prompt states them, but a rail the
    system doesn't enforce isn't a rail):
      - a level correction WITHIN the {new_grad, entry} filter equivalence is
        REJECTED: the label stays, needs_human is set, and the rejected change
        lands in judge_notes (churn inside the equivalence changes nothing a
        user sees, and measured judge level changes there were harmful);
      - any other level correction is REJECTED when the judge's own confidence
        is below JUDGE_LEVEL_CONFIDENCE_MIN (other corrections still apply).

    Subcategory rails (four, all code-enforced):
      A. KNOB KILL SWITCH — with `judge:subcategory_corrections` off, drop
         `subcategories` from the corrections before anything else. The knob
         exists so the lift can be MEASURED and killed in one command.
      B. CONFIDENCE BAR — a subcategory correction below
         JUDGE_SUBCATEGORY_CONFIDENCE_MIN (or with conf None) is rejected and
         counted. ⚠ It does NOT force needs_human: that branch is reserved for
         the new_grad/entry equivalence, and forcing it here would flood triage.
      C. TRI-STATE PRESERVATION — ⚠ when the stored value is NULL and the judge
         supplied nothing, the merged value STAYS NULL. A judge pass must never
         turn "never evaluated" into "evaluated, none apply": that silently
         drains the backfill queue and makes the coverage number that gates the
         90% reveal a lie.
      D. CATEGORY CONSISTENCY — after `category` resolves, a non-SWE category
         FORCES subcategories to `[]`, not NULL (the row WAS evaluated and the
         answer is "not applicable"), regardless of what the judge said. Mirrors
         how a rejected level correction also drops the derived level_includes.

    Rejected corrections are counted in the returned dict's
    ``rejected_corrections`` key (popped by the caller — not persisted)."""
    # Same "never raises on bad data" hardening as the classify recorder: a
    # non-dict corrections payload is dropped, and scalar fields are coerced —
    # a dict conf would otherwise raise at the floor comparisons below before
    # even reaching the sqlite bind.
    raw_corr = verdict.get("corrections")
    corr = dict(raw_corr) if isinstance(raw_corr, dict) else {}
    if raw_corr and not isinstance(raw_corr, dict):
        logger.warning(
            "record-judge: job_listing_id=%s corrections is %s, not a dict; ignoring",
            base["job_listing_id"], type(raw_corr).__name__,
        )
    proposed_any = bool(corr)
    passed = bool(verdict.get("passed", verdict.get("judge_pass", True)))
    conf = _coerce_confidence(verdict.get("confidence", verdict.get("judge_confidence")))
    notes = _coerce_text_field(verdict.get("notes", verdict.get("judge_notes")))
    reasoning = _coerce_text_field(verdict.get("reasoning", verdict.get("judge_reasoning")))
    judge_latency_ms = _coerce_int_field(verdict.get("judge_latency_ms"))

    rejected_notes: list[str] = []
    force_needs_human = False

    # RAIL A — the knob kill switch, applied BEFORE anything else so a disabled
    # knob is indistinguishable from a judge that never proposed the facet.
    if not subcategory_corrections and "subcategories" in corr:
        corr.pop("subcategories")
        rejected_notes.append(
            "subcategories correction dropped (judge:subcategory_corrections is off)"
        )

    # RAIL B — the confidence bar. Rejected, counted, noted in the same phrasing
    # as the level rejections — and DELIBERATELY not needs_human-forcing.
    if "subcategories" in corr and (
        conf is None or conf < JUDGE_SUBCATEGORY_CONFIDENCE_MIN
    ):
        proposed = corr.pop("subcategories")
        rejected_notes.append(
            f"subcategories correction ->{proposed!r} rejected "
            f"(judge confidence {conf} < {JUDGE_SUBCATEGORY_CONFIDENCE_MIN})"
        )

    if corr.get("level") is not None and corr["level"] != base["level"]:
        base_level, corr_level = base["level"], corr["level"]
        if base_level in _LEVEL_EQUIVALENCE and corr_level in _LEVEL_EQUIVALENCE:
            corr.pop("level")
            corr.pop("level_includes", None)  # derived from the rejected level
            force_needs_human = True
            rejected_notes.append(
                f"level correction {base_level}->{corr_level} rejected "
                "(new_grad/entry filter equivalence); flagged needs_human"
            )
        elif conf is None or conf < JUDGE_LEVEL_CONFIDENCE_MIN:
            corr.pop("level")
            corr.pop("level_includes", None)
            rejected_notes.append(
                f"level correction {base_level}->{corr_level} rejected "
                f"(judge confidence {conf} < {JUDGE_LEVEL_CONFIDENCE_MIN})"
            )
    for note in rejected_notes:
        logger.warning(
            "record-judge: job_listing_id=%s %s", base["job_listing_id"], note
        )

    def pick(field: str, current: Any) -> Any:
        return corr[field] if field in corr and corr[field] is not None else current

    category = pick("category", base["category"])
    level = pick("level", base["level"])
    level_includes = pick("level_includes", json.loads(base["level_includes"] or "[]"))
    tags = pick("tags", json.loads(base["tags"] or "[]"))
    locations = pick("locations", json.loads(base["locations"] or "[]"))

    # RAIL C — TRI-STATE PRESERVATION. The default is the row's CURRENT STORED
    # value, so a judge that says nothing changes nothing. ⚠ `pick` treats an
    # explicit None as "not supplied", which is exactly right here: NULL stays
    # NULL, and only a real list from the judge can move it.
    stored_subcats = base.get("subcategories")
    if isinstance(stored_subcats, str):
        try:
            stored_subcats = json.loads(stored_subcats)
        except (TypeError, ValueError):
            stored_subcats = None
    subcategories = pick("subcategories", stored_subcats)

    # OR in the pre-judge flag: a row classify flagged needs_human (e.g. an
    # invalid slug nulled at ingest, E4) must STAY flagged even if a confident
    # judge verdict says needs_human=false — never silently clear it (E16).
    needs_human = (
        bool(verdict.get("needs_human", False))
        or bool(base.get("needs_human"))
        or force_needs_human
    )
    if conf is not None and conf < floor:
        needs_human = True

    category, level, bad = tax.validate_facets(category, level)

    # RAIL D — CATEGORY CONSISTENCY, applied AFTER category resolves. A non-SWE
    # category forces `[]` — NOT NULL: the row WAS evaluated and the answer is
    # "not applicable", so it must leave the backfill queue rather than sit in it
    # forever.
    if category != tax.SUBCATEGORY_PARENT and subcategories is not None:
        if subcategories:
            rejected_notes.append(
                f"subcategories forced to [] (category is {category!r}, "
                f"not {tax.SUBCATEGORY_PARENT!r})"
            )
        subcategories = []

    subcategories, sub_bad, sub_warnings = tax.validate_subcategories(
        category, subcategories
    )

    # ⚠ THE JUDGE'S SUBCATEGORY PROVENANCE + CONFIDENCE. Decided HERE because
    # this is the only place that knows BOTH the stored label and the merged one.
    #
    # Before this, a judge pass wrote `subcategories` and left the other two
    # columns exactly as classify had set them, so:
    #   classify stores (["backend"], 0.91, 'classify'); the judge moves the
    #   category to business_ops; RAIL D forces `[]` -> the row persists as
    #   ('[]', 0.91, 'classify'). A confidence with no label behind it, attributed
    #   to the lane that did not write it. A plain label CHANGE
    #   (["backend"] -> ["frontend"]) kept 0.91 too — now measuring a label that
    #   no longer exists.
    subcategory_changed = subcategories != stored_subcats
    if subcategory_changed:
        # The judge emits NO per-label confidence — its `confidence` is a VERDICT
        # confidence, a different quantity — so NULL is the only honest value for
        # a label it just moved. `[]` forced by RAIL D counts as a change.
        subcategory_confidence = None
        # ...and `judge` is one of the five tax.SUBCATEGORY_SOURCES. Without this
        # stamp the source still reads 'classify' after a judge overwrite, so a
        # rollback scoped to the classify lane reverts the wrong set of rows.
        subcategory_source: str | None = (
            None if subcategories is None else "judge"
        )
    else:
        # The judge said nothing about subcategories (or agreed): classify's
        # confidence AND provenance stand untouched.
        subcategory_confidence = base.get("subcategory_confidence")
        subcategory_source = base.get("subcategory_source")
    # SHARED CONTRACT 1.2 A, as a hard rail over whichever branch ran: confidence
    # is null unless the array is a NON-EMPTY list, and a null array carries no
    # source at all.
    subcategory_confidence = _subcategory_confidence(
        subcategories, subcategory_confidence
    )
    if subcategories is None:
        subcategory_source = None

    bad = bad + sub_bad
    for warning in sub_warnings:
        logger.info(
            "record-judge: job_listing_id=%s subcategory rule applied: %s",
            base["job_listing_id"], warning,
        )
    if bad:
        needs_human = True
        for facet, value in bad:
            logger.warning(
                "record-judge: job_listing_id=%s judge produced invalid %s=%r "
                "(not in taxonomy); nulled + flagged needs_human",
                base["job_listing_id"], facet, value,
            )

    if rejected_notes:
        suffix = " | ".join(rejected_notes)
        notes = f"{notes} | {suffix}" if notes else suffix

    return {
        "job_listing_id": base["job_listing_id"],
        "source_id": base.get("source_id"),
        "category": category,
        "level": level,
        "level_includes": _coerce_json_field(level_includes),
        "tags": _coerce_json_field(tags),
        "locations": _coerce_json_field(locations),
        # ⚠ NOT _coerce_json_field, which collapses NULL to '[]' and would
        # destroy the tri-state on every judge pass.
        "subcategories": _coerce_subcategories_field(subcategories),
        # ⚠ These two ride ALONGSIDE the array and record_judge writes all three
        # in ONE update — a subcategory can never be persisted apart from its
        # confidence and its provenance.
        "subcategory_confidence": subcategory_confidence,
        "subcategory_source": subcategory_source,
        # a proposed-but-rejected correction is still not a clean pass
        "judge_pass": passed and not proposed_any,
        "judge_confidence": conf,
        "judge_notes": notes,
        "judge_reasoning": reasoning,
        "judge_latency_ms": judge_latency_ms,
        "needs_human": needs_human,
        "rejected_corrections": len(rejected_notes),
    }


# ---- write-back (Stage D) --------------------------------------------------
def _cmd_write_back(args: argparse.Namespace) -> int:
    from job_enricher.writeback import write_back

    result = write_back(Store())
    print(f"write-back: {json.dumps(result)}")
    # Distinguish "nothing to send" (a clean no-op) from "N rows still unsent
    # after retries" (JVN rejects and/or failed batches). The latter is a tick
    # error signal so /enrich-tick can close the tick with status=error (E7).
    if result["unsent"] > 0:
        logger.error(
            "write-back: %d row(s) still unsent after retries (%d failed batch(es)); "
            "they retry next tick", result["unsent"], result["errors"],
        )
        return 1
    return 0


# ---- observability ---------------------------------------------------------
def _cmd_health(args: argparse.Namespace) -> int:
    store = Store()
    # ⚠ Assert BOTH taxonomy files exist and print the version. This is the
    # deploy sanity check (deploy.sh step 6), so a missing SUBCATEGORIES.md is
    # caught HERE rather than at the first classify — where read_subcategory_rubric
    # would raise inside a tick, or (worse, if it ever returned '') the backfill
    # lane would label from nothing and report success.
    missing = [
        str(path)
        for path in (tax.skill_path(), tax.subcategory_rubric_path())
        if not path.exists()
    ]
    if missing:
        print(
            "health: MISSING taxonomy file(s): " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2
    print(f"taxonomy_version: {tax.taxonomy_version()}", file=sys.stderr)
    print(json.dumps(collect_health(store)))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    return _cmd_health(args)


# ---- eval ------------------------------------------------------------------
def _cmd_build_golden(args: argparse.Namespace) -> int:
    from job_enricher.eval.golden import build_golden_set

    path = build_golden_set(n=args.n, stratify="company")
    print(f"build-golden-set: wrote {path}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from job_enricher.eval.report import run_eval

    code = run_eval(
        golden_set=args.set, judge=args.judge, gate=args.gate, baseline=args.baseline,
        allow_draft=args.allow_draft, engine=args.engine, reasoning=args.reasoning,
        tag=args.tag, facet=args.facet,
        gate_groups=tuple(args.gate_group) if args.gate_group else None,
        model=args.model, conf_threshold=args.conf_threshold,
    )
    return code


# ---- prelabel / review (the D1 + D3 gold-pool bootstrap) -------------------
def _cmd_prelabel(args: argparse.Namespace) -> int:
    """Pre-label a drawn pool with an INDEPENDENT model, for human review.

    Exit 2 is the independence refusal — see eval/prelabel.py's module
    docstring for why a model agreeing with itself is not evidence."""
    from job_enricher.eval.prelabel import IndependenceError, run_prelabel

    try:
        path = run_prelabel(
            facet=args.facet, engine=args.engine, model=args.model,
            under_test=args.under_test, seed=args.seed, draw=args.draw,
            batch=args.batch, out=Path(args.out) if args.out else None,
        )
    except IndependenceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    print(
        f"prelabel: facet={data['facet']} pool={data['pool_size']} "
        f"model={data['prelabel_engine']}/{data['prelabel_model']} "
        f"seed={data['seed']} -> {path}"
    )
    return 0


def _cmd_review_build(args: argparse.Namespace) -> int:
    from job_enricher.eval.prelabel import build_review

    rpath, apath, header = build_review(
        facet=args.facet, audit_rate=args.audit_rate, seed=args.seed,
        prelabel_file=Path(args.prelabel_file) if args.prelabel_file else None,
        out=Path(args.out) if args.out else None,
    )
    tc = header["tier_counts"]
    print(
        f"review-build: facet={header['facet']} tiers A={tc['A']} B={tc['B']} "
        f"C={tc['C']} audit={header['audit_target']} "
        f"(rate={header['audit_rate']}, independent="
        f"{header['corroborator_independent']}, promote="
        f"{header['promote_agreements']}) -> {rpath}"
    )
    print(f"review-build: non-audited agreements -> {apath}")
    return 0


def _cmd_review_render(args: argparse.Namespace) -> int:
    from job_enricher.eval.prelabel import render_review_html, review_path

    src = Path(args.review_file) if args.review_file else review_path(args.facet)
    review = json.loads(src.read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else src.with_suffix(".html")
    out.write_text(render_review_html(review), encoding="utf-8")
    print(f"review-render: {len(review['entries'])} rows -> {out}")
    return 0


def _cmd_review_apply(args: argparse.Namespace) -> int:
    from job_enricher.eval.prelabel import apply_review

    result = apply_review(
        facet=args.facet, threshold=args.threshold,
        review_file=Path(args.review_file) if args.review_file else None,
    )
    v = result["verdict"]
    print(
        f"review-apply: facet={v['facet']} decided={result['decided']} "
        f"audited={v['reviewed']} errors={v['errors']} "
        f"error_rate={v['error_rate']} threshold={v['threshold']} "
        f"passed={v['passed']} promoted={result['promoted']}"
    )
    if result["undecided"]:
        print(
            f"review-apply: {len(result['undecided'])} row(s) still UNDECIDED — "
            f"{', '.join(result['undecided'][:10])}"
            + (" …" if len(result["undecided"]) > 10 else "")
        )
    if not v["passed"]:
        print(
            "review-apply: audit NOT passed — nothing promoted, and "
            "load_truth will drop every prelabel_agreed row. This is the "
            "honest branch, not a failure to work around."
        )
    return 0


# ---- the weak rule baseline (EV-11) ---------------------------------------
# ⚠ G2: v7 must beat this on `subcategory_set_f1` by at least this much. A
# model that cannot out-label a REGEX on the titles the regex can type has no
# business shipping.
#
# ⚠ CORRECTION — IT IS NOT A DAY-ONE GATE. The rule labeler needs no human
# labels, but SCORING it does: `score()` compares the rule's predictions against
# `load_truth(facet='subcategory')`, which returns 0 rows until the EV-9b pool
# run lands. On an empty pool every metric is 0.0 and "beat 0.0 by 0.10" is a
# free pass. The card is therefore stamped `gate_ready` and the command fails
# closed. See EVAL-V6-V7-PROTOCOL.md's G2 row: CANNOT RUN until P4.
WEAK_BASELINE_MARGIN = 0.10


def _cmd_subcategory_weak_baseline(args: argparse.Namespace) -> int:
    """Run `subcategory_rules` over the gold-SWE pool and score it.

    ⚠ CRITICAL SCOPING: ON THE GOLDEN POOL THIS USES `label_from_title` ONLY.
    The seed's `tags` field is a gold LABEL produced by an earlier draft run —
    it is what `score()` compares predictions against — so scoring the tag layer
    against it is label leakage. It would make the weak baseline look
    artificially strong and therefore make the gate artificially hard FOR THE
    WRONG REASON. The tag layer's real contribution is unmeasurable on this pool
    until company tags reach the seed (named follow-up: expose `details->'tags'`
    in JVN's `_JOB_PROJECTION` plus a `company_tags` seed field; NOT blocking).
    """
    from job_enricher.eval.golden import SCORECARD_DIR, load_seed, load_truth
    from job_enricher.eval.scoring import score
    from job_enricher.subcategory_rules import label_from_title

    rows = load_seed()
    swe = [r for r in rows if r.get("category") == tax.SUBCATEGORY_PARENT]
    predictions = [
        {
            "job_listing_id": r.get("job_listing_id"),
            "source_id": r.get("source_id"),
            # The rule labeler decides a SUBCATEGORY only — it never touches the
            # category — so the gold parent is echoed through. That is what makes
            # `subcategory_accuracy_given_parent_correct` readable here and keeps
            # a spurious leak out of the artifact.
            "category": r.get("category"),
            "subcategories": label_from_title(r.get("title")),
            # A rule has no confidence, and inventing one would pollute the
            # subcategory calibration with a constant.
            "subcategory_confidence": None,
        }
        for r in swe
    ]
    art_dir = REPO_ROOT / "golden" / "baselines" / "weak_rule"
    art_dir.mkdir(parents=True, exist_ok=True)
    art_path = art_dir / "predictions.weak_rule.json"
    artifact = {
        # ⚠ STAMPED so nobody later mistakes this for the PRODUCTION rule layer,
        # which also runs the tag layer.
        "input_mode": "title_only",
        "generated_by": "job_enricher.subcategory_rules.label_from_title",
        "row_set": "gold-SWE seed rows (category == software_engineering)",
        "n": len(predictions),
        "predictions": predictions,
    }
    art_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    truth = load_truth(facet="subcategory")
    card = score(predictions, truth).to_dict()
    card["input_mode"] = "title_only"
    card["gold_quality"] = "weak_rule"
    card["baseline_kind"] = "weak_rule"
    card["g2_margin"] = WEAK_BASELINE_MARGIN
    # ⚠ THE CARD STATES WHETHER IT CAN GATE. Scoring against an EMPTY gold pool
    # produces a full card of 0.0s that looks like a baseline and is not one:
    # "beat 0.0 by 0.10" is a free pass, and `subcategory_set_f1: 0.0` alone
    # does not say why. `gate_ready` is computed from the pool the card was
    # scored on, so G2 has something to refuse on instead of a silent zero.
    card["gate_ready"] = card["subcategory_n"] > 0
    card["gate_blocked_reason"] = None if card["gate_ready"] else (
        "the subcategory gold pool is EMPTY — load_truth(facet='subcategory') "
        "returned 0 rows, so every metric on this card is a placeholder 0.0. "
        "G2 cannot fire until the EV-9b pool run lands."
    )
    SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
    card_path = SCORECARD_DIR / "baseline.weak_rule.json"
    card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")

    typed = sum(1 for p in predictions if p["subcategories"])
    print(
        f"subcategory-weak-baseline: {len(predictions)} gold-SWE rows, "
        f"{typed} typed by the title layer -> {art_path}"
    )
    print(
        f"subcategory-weak-baseline: scored over "
        f"{card['subcategory_n']} gold subcategory row(s), "
        f"set_f1={card['subcategory_set_f1']} -> {card_path}"
    )
    if not card["gate_ready"]:
        print(
            "subcategory-weak-baseline: ⚠ the subcategory gold pool is EMPTY, "
            "so the scored card is a placeholder stamped gate_ready=false — G2 "
            "CANNOT fire until EV-9b has run. The prediction artifact above is "
            "complete and durable; re-run this command once the pool exists.",
            file=sys.stderr,
        )
        # FAIL CLOSED: a placeholder card is not a baseline. Exit 2 so a run
        # that produced no gate cannot read as one in a scrollback or CI log.
        # `--allow-empty-pool` is how EV-11 commits the durable artifact today.
        if not getattr(args, "allow_empty_pool", False):
            return 2
    return 0


# ---- reenrich (MANUAL taxonomy re-processing) -----------------------------
_TAXONOMY_VERSION_RE = re.compile(r"^v(\d+)\+(\S+)$")

# Above this many matched rows, `reenrich` REFUSES without --yes-i-mean-all.
# WHY: at the v6 -> v7 bump `reenrich --taxonomy-below v7+<hash>` matches EVERY
# v6 row — the entire ~19.4k-row corpus — and the command DELETEs each
# enrichment and flips the inbox row back to 'cleaned' with no undo. That is
# roughly 40 days of worker time. The threshold and the flag name are
# DELIBERATELY IDENTICAL to `subcategory-reset`'s (BF-14) so the two dangerous
# commands in this repo behave the same way under muscle memory.
REENRICH_CONFIRM_THRESHOLD = 500


def _cmd_reenrich(args: argparse.Namespace) -> int:
    """Re-queue rows whose taxonomy_version is strictly BELOW the given
    'v<N>+<hash>' (smaller declared N). Rows at the same N with a different
    hash are NOT below (hashes are unordered) — they are warned and left
    alone. Unversioned rows count as below.

    THIS COMMAND IS DESTRUCTIVE AND HAS NO UNDO: it DELETEs the enrichment row
    and flips inbox.status back to 'cleaned' so the row is re-classified from
    scratch. Three guards, all added after the v7 bump made an unguarded run a
    corpus-wide event:
      * `--dry-run` counts and prints, mutating NOTHING (do this first, always);
      * above REENRICH_CONFIRM_THRESHOLD matched rows it REFUSES unless
        `--yes-i-mean-all` is passed;
      * `--limit` bounds how many rows are actually reset.
    """
    if _TAXONOMY_VERSION_RE.match(args.taxonomy_below) is None:
        print(
            f"reenrich: --taxonomy-below must look like 'v<N>+<hash>' "
            f"(e.g. v2+3f9a1c2b8e04), got {args.taxonomy_below!r}",
            file=sys.stderr,
        )
        return 2
    limit = getattr(args, "limit", None)
    store = Store()
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT job_listing_id, source_id, taxonomy_version FROM enrichments"
        ).fetchall()
        matched = [
            r for r in rows if _version_below(r["taxonomy_version"], args.taxonomy_below)
        ]
        # COUNT FIRST, ALWAYS — the count is computed before a single mutation so
        # both the dry run and the refusal below see the true blast radius.
        print(
            f"reenrich: {len(matched)} rows match taxonomy below "
            f"{args.taxonomy_below!r} (of {len(rows)} enrichments)"
        )
        if getattr(args, "dry_run", False):
            print("reenrich: --dry-run — nothing was modified")
            return 0
        if len(matched) > REENRICH_CONFIRM_THRESHOLD and not getattr(
            args, "yes_i_mean_all", False
        ):
            print(
                f"reenrich: REFUSING — {len(matched)} rows exceeds "
                f"{REENRICH_CONFIRM_THRESHOLD}. Re-run with --yes-i-mean-all if "
                f"you really mean to re-queue them all, or bound it with --limit. "
                f"Nothing was modified.",
                file=sys.stderr,
            )
            return 2
        if limit is not None:
            matched = matched[:limit]
        target = 0
        for r in matched:
            conn.execute(
                "UPDATE inbox SET status='cleaned' "
                "WHERE source_id=? AND job_listing_id=? AND clean_description IS NOT NULL",
                (r["source_id"], r["job_listing_id"]),
            )
            conn.execute(
                "DELETE FROM enrichments WHERE source_id=? AND job_listing_id=?",
                (r["source_id"], r["job_listing_id"]),
            )
            target += 1
    print(f"reenrich: reset {target} rows below taxonomy {args.taxonomy_below!r}")
    return 0


def _version_below(current: str | None, threshold: str) -> bool:
    """True when `current` is strictly below `threshold` under the
    'v<N>+<hash>' scheme (smaller declared N). Same-N-different-hash is NOT
    below — content hashes carry no ordering — and logs a warning so a
    hash-only drift is visible. Missing/unparseable `current` predates
    versioning and counts as below.

    THE v7 CONSEQUENCE, WRITTEN DOWN SO NOBODY EXPECTS OTHERWISE: from v7 on,
    `taxonomy_version()` folds BOTH SKILL.md and SUBCATEGORIES.md into the hash
    while the declared N stays the same. Editing the rubric therefore moves the
    hash and NOT the N — which is same-N-different-hash, which is NOT below — so
    **rubric-only edits will NEVER be picked up by `reenrich`.** That is the
    intended behaviour (a rubric tweak must not re-queue the corpus), but it
    means a deliberate re-enrichment after a rubric change needs an explicit
    declared-version bump, not just a rubric edit."""
    t = _TAXONOMY_VERSION_RE.match(threshold)
    if t is None:
        raise ValueError(f"invalid taxonomy version threshold {threshold!r}")
    c = _TAXONOMY_VERSION_RE.match(current or "")
    if c is None:
        return True
    current_n, current_hash = int(c.group(1)), c.group(2)
    threshold_n, threshold_hash = int(t.group(1)), t.group(2)
    if current_n < threshold_n:
        return True
    if current_n == threshold_n and current_hash != threshold_hash:
        logger.warning(
            "reenrich: %s has the same declared version as %s but a different "
            "content hash — NOT below (hashes are unordered); row left alone",
            current, threshold,
        )
    return False


# ---- golden-merge (human corrections -> gold labels) -----------------------
def _cmd_golden_merge(args: argparse.Namespace) -> int:
    """Pull human admin corrections from JVN and fold them into the golden
    seed as label_source='human' rows — the online path that turns triage work
    into real ground truth for the regression gate.

    ⚠ EXITS 2 WHEN THE LIVE FEED OMITS THE v7 KEYS (`subcategories`,
    `taxonomy_version`). Without that check the command's success line is a lie
    by omission: if ADM-5 slips, every correction is silently pre-v7, the merge
    reports matched/upgraded counts, exits 0 — and writes no subcategory gold
    at all. `--allow-pre-v7` is the escape hatch for a deliberate
    category-only merge; it still prints the violation."""
    from job_enricher.eval.golden import merge_corrections
    from job_enricher.jvn_client import JVNClient, missing_v7_correction_keys

    corrections = JVNClient().get_corrections(since=args.since, limit=args.limit)
    # ⚠ INSPECT THE LIVE FEED, NOT JUST A FIXTURE. `missing_v7_correction_keys`
    # existed with a unit test over literal dicts as its only caller, so a
    # /corrections feed shipped without `subcategories`/`taxonomy_version`
    # (i.e. ADM-5 slipping) produced a merge that printed matched=N upgraded=N,
    # exited 0, and wrote ZERO subcategory gold. The check now runs on what JVN
    # actually returned.
    incomplete = {
        f"{c.get('source_id')}/{c.get('job_listing_id')}": missing
        for c in corrections
        if (missing := missing_v7_correction_keys(c))
    }
    report = merge_corrections(corrections)
    print(
        f"golden-merge: matched={report['matched']} upgraded={report['upgraded']} "
        f"unmatched={report['unmatched']} "
        f"subcategory_upgraded={report['subcategory_upgraded']}"
    )
    if report["unmatched"]:
        # ⚠ NOT DISCARDED, PARKED — and the seed deliberately does NOT grow from
        # this feed. Saying so on the line itself is what stops a reader from
        # assuming the correction loop alone will reach GATE_MIN_N.
        print(
            f"golden-merge: unmatched={report['unmatched']} "
            f"(parked in {UNMATCHED_WORKLIST_REL} — the seed does NOT grow "
            "from this feed)"
        )
    if incomplete:
        # ⚠ FAIL CLOSED. The feed violates the v7 contract, so this run CANNOT
        # have written subcategory gold no matter what `upgraded` says. Exit 2
        # rather than 0 so a slipped ADM-5 is a red command, not a green
        # no-op. The category half of the merge above is real work and is kept
        # — `--allow-pre-v7` is the documented escape hatch for exactly that
        # case, and it still prints this line.
        missing_keys = sorted({k for ks in incomplete.values() for k in ks})
        named = ", ".join(list(incomplete)[:5]) + (" …" if len(incomplete) > 5 else "")
        print(
            f"golden-merge: v7 CONTRACT VIOLATION — {len(incomplete)}/"
            f"{len(corrections)} correction(s) omit {missing_keys} "
            f"({named}). ADM-5 has not shipped this feed, so "
            f"subcategory_upgraded={report['subcategory_upgraded']} and no "
            "subcategory gold can be written by this run.",
            file=sys.stderr,
        )
        if not getattr(args, "allow_pre_v7", False):
            return 2
    return 0


# ---- metrics push (best-effort observability channel) ----------------------
def _cmd_metrics_push(args: argparse.Namespace) -> int:
    """Assemble + POST the latest (or given) tick's metrics to JVN.

    BEST-EFFORT by contract: a metrics failure must NEVER fail a tick — any
    error is logged and the command exits 0 (exit 2 only under --strict)."""
    from job_enricher.jvn_client import JVNClient
    from job_enricher.metrics import build_metrics_payload

    store = Store()
    try:
        payload, scorecard_hash = build_metrics_payload(store, tick_id=args.tick_id)
        if payload is None:
            print("metrics-push: no tick to report")
            return 0
        JVNClient().post_metrics(payload)
        if scorecard_hash is not None:
            store.set_meta(LAST_SCORECARD_HASH_KEY, scorecard_hash)
        print(
            f"metrics-push: ok tick_uuid={payload['tick_uuid']} "
            f"status={payload['status']}"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — best-effort boundary by contract
        logger.warning("metrics-push failed (best-effort, never fails a tick): %s", exc)
        print(f"metrics-push: failed — {exc}", file=sys.stderr)
        return 2 if args.strict else 0


# ---- serve (optional edge) -------------------------------------------------
def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from job_enricher.config import settings

    uvicorn.run("job_enricher.server:app", host="127.0.0.1", port=settings.edge_port)
    return 0


# ---- dashboard (local read+edit observability UI) --------------------------
def _cmd_dashboard(args: argparse.Namespace) -> int:
    """Run the local dashboard (JSON API + built SPA). LOCALHOST ONLY by default:
    it can edit the runtime knobs over an unauthenticated endpoint, so a
    non-loopback --host is REFUSED (exit 2) unless --allow-remote is passed — and
    even then it must never be tunneled. --api-only serves just the API (pair with
    the Vite dev server on :5173 for front-end iteration).

    Refuses to serve from a `.claude/worktrees/` checkout (exit 2): worktrees are
    scratch/ephemeral, so a dashboard started from one silently freezes at
    whatever commit that worktree happened to be on — see
    docs/handoffs/2026-07-12-prod-monitoring-after-ollama-cutover.md for the
    incident this guards against. Prefer `scripts/run_dashboard.sh`, which always
    builds and serves the checked-out commit and prints its branch + sha."""
    import subprocess
    import uvicorn

    from job_enricher.config import settings

    if ".claude/worktrees" in str(REPO_ROOT):
        logger.error(
            "dashboard: refusing to serve from a git worktree (%s) — worktrees "
            "are scratch/ephemeral and go stale silently. Run the dashboard from "
            "the main checkout instead, e.g. scripts/run_dashboard.sh.",
            REPO_ROOT,
        )
        return 2
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        branch = None
    if branch and branch != "main":
        logger.warning(
            "dashboard: serving from branch %r, not main — the UI may be stale "
            "or missing merged fixes. `git switch main && git pull --ff-only` "
            "first unless you're intentionally iterating on a feature branch.",
            branch,
        )

    host = args.host
    is_loopback = host in ("127.0.0.1", "localhost")
    if not is_loopback and not args.allow_remote:
        logger.error(
            "dashboard: refusing to bind %s — this exposes the unauthenticated "
            "knob editor beyond localhost. Pass --allow-remote to override "
            "(and never place the dashboard behind a tunnel).",
            host,
        )
        return 2
    if not is_loopback:
        logger.warning(
            "dashboard: binding %s exposes the knob editor beyond localhost — "
            "only do this on a trusted network and never tunnel it",
            host,
        )
    if args.api_only:
        os.environ["DASHBOARD_SERVE_STATIC"] = "0"
    port = args.port or settings.dashboard_port
    uvicorn.run("job_enricher.dashboard:app", host=host, port=port)
    return 0


# ---- small lookups ---------------------------------------------------------
def _enrichment_map(store: Store, ids: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """Enrichment rows keyed by the composite (source_id, job_listing_id)."""
    if not ids:
        return {}
    ph = ",".join("?" for _ in ids)
    with store.connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM enrichments WHERE job_listing_id IN ({ph})", ids
        ).fetchall()
    return {(r["source_id"], r["job_listing_id"]): dict(r) for r in rows}


# ---- backfill scope import (P0-4) ------------------------------------------
# ⚠ REFRESH POLICY. The scope is a POINT-IN-TIME export of JVN's OPEN-SWE jobs
# and jobs open and close overnight. The night's run refuses (exit 2) on a scope
# older than this, or on an empty scope, because **a silently-empty scope makes
# `--open-only` a no-op that reports success.**
# ONE number: re-exported from store, where `rows_needing_subcategory(open_only=True)`
# enforces it structurally by raising ScopeUnavailableError.


def _read_scope_ndjson(path: Path) -> list[tuple[str, str]]:
    """One JSON object per line: {"source_id": ..., "job_listing_id": ...}.
    A whole-file JSON array is also accepted, since psql -At is easy to get
    wrong and a wrong shape must be an error, not an empty import."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.lstrip().startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    pairs: list[tuple[str, str]] = []
    for r in rows:
        sid, jid = r.get("source_id"), r.get("job_listing_id")
        if sid and jid:
            pairs.append((str(sid), str(jid)))
    return pairs


def _cmd_subcategory_scope_import(args: argparse.Namespace) -> int:
    """Import the OPEN-SWE scope exported by scripts/export_open_swe_scope.sql.

    Idempotent upsert on (source_id, job_listing_id). Prints
    `imported=<N> matched_local=<M> missing_local=<N-M>`, and ⚠ **`matched_local`
    is PARAM_BACKFILL_DENOMINATOR** — it replaces the 8,126 placeholder
    everywhere downstream, including the 90% coverage gate. 8,126 is a JVN-side
    OPEN-SWE count, NOT a backfillable count."""
    path = Path(args.json_file)
    if not path.exists():
        print(f"subcategory-scope-import: no such file {path}", file=sys.stderr)
        return 2
    try:
        pairs = _read_scope_ndjson(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"subcategory-scope-import: unreadable {path}: {exc}", file=sys.stderr)
        return 2
    if not pairs:
        print(
            f"subcategory-scope-import: REFUSING — {path} yielded zero pairs. An "
            f"empty scope makes --open-only a no-op that reports success.",
            file=sys.stderr,
        )
        return 2
    store = Store()
    imported, matched = store.import_backfill_scope(pairs)
    print(
        f"imported={imported} matched_local={matched} "
        f"missing_local={imported - matched}"
    )
    print(
        f"subcategory-scope-import: matched_local={matched} is "
        f"PARAM_BACKFILL_DENOMINATOR — record it in "
        f"docs/RUNBOOK-subcategory-backfill.md before the run."
    )
    return 0


def check_backfill_scope_freshness(
    store: Store, max_age_hours: float = SCOPE_MAX_AGE_HOURS
) -> str | None:
    """None when the scope is fresh and non-empty; otherwise the refusal reason.

    Called by the night's run so a stale or empty scope is an EXIT 2, not a
    silently successful no-op. Delegates to the store so the CLI's pre-flight
    and the selector's own refusal can never disagree."""
    return store.scope_refusal_reason(max_age_hours)


# ---- BF-9: the night's subcategory backfill run ----------------------------
def resolve_deadline(
    until: str | None,
    tz: str,
    max_seconds: int | None,
    now: datetime | None = None,
) -> datetime | None:
    """`--until` is an ABSOLUTE local wall-clock time, resolved to its NEXT
    occurrence in `zoneinfo.ZoneInfo(tz)` — Python >= 3.11, so DST-correct for
    Central Time. Combined with `--max-seconds` as `min(...)`."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    candidates: list[datetime] = []
    now = now or datetime.now(timezone.utc)
    if until:
        zone = ZoneInfo(tz)
        hh, _, mm = until.partition(":")
        local_now = now.astimezone(zone)
        target = local_now.replace(
            hour=int(hh), minute=int(mm or 0), second=0, microsecond=0
        )
        if target <= local_now:
            target += timedelta(days=1)  # the NEXT occurrence
        candidates.append(target.astimezone(timezone.utc))
    if max_seconds:
        candidates.append(now + timedelta(seconds=max_seconds))
    return min(candidates) if candidates else None


def _cmd_subcategory_backfill(args: argparse.Namespace) -> int:
    """Label the SWE backlog's subcategories, off the live lane.

    ⚠ There is NO `--concurrency` flag, deliberately, and there is no
    `backfill:concurrency` knob. `ChunkEngine._call_with_repair` is strictly
    sequential, nothing in `ChunkEngine` supports parallel chunks, and a
    threadpool would multiply SQLite write contention against the live tick
    (`busy_timeout` 5000 ms). The levers for wall time are `--batch` and the
    model tier, both measured by `P0-5`. Do not re-add the option on a slow
    night."""
    import signal

    from job_enricher import backfill as bfl
    from job_enricher.engines import build_engine

    store = Store()
    if args.open_only:
        refusal = check_backfill_scope_freshness(store)
        if refusal is not None:
            print(f"subcategory-backfill: REFUSED — {refusal}", file=sys.stderr)
            return 2

    lock_path = store.db_path.parent / bfl.BACKFILL_LOCK_NAME
    acquired, reason = lock_mod.try_acquire(lock_path, stale_after_hours=12)
    if not acquired:
        print(f"subcategory-backfill: skipped — {reason}")
        return 75

    stop_path = store.db_path.parent / bfl.STOP_SENTINEL_NAME

    def _on_signal(signum, _frame):
        # ⚠ Finish the CHUNK in flight, then stop: the sentinel is honoured at
        # the next chunk boundary, which is what protects a write in flight.
        logger.warning("subcategory-backfill: signal %s — stopping after this chunk", signum)
        try:
            stop_path.touch()
        except OSError:
            pass

    previous = [
        (sig, signal.signal(sig, _on_signal))
        for sig in (signal.SIGTERM, signal.SIGINT)
    ]
    try:
        engine_kind, model = _stage_engine_model(
            store, "classify", None, args.model
        )
        engine = build_engine(engine_kind, model=model)
        deadline = resolve_deadline(args.until, args.tz, args.max_seconds)
        probe_path = None
        if args.dry_run:
            probe_path = Path(args.probe_json) if args.probe_json else (
                store.db_path.parent
                / f"backfill-probe-{now_iso().replace(':', '-')}.json"
            )
        outcome = bfl.run_backfill(
            store, engine, limit=args.limit, batch=args.batch,
            max_attempts=None, open_only=args.open_only, deadline=deadline,
            dry_run=args.dry_run, model=model, engine_name=engine_kind,
            probe_path=probe_path, stop_path=stop_path,
        )
    finally:
        for sig, handler in previous:
            signal.signal(sig, handler)
        lock_mod.release(lock_path)

    head = f"subcategory-backfill: status={outcome.status}"
    if outcome.aborted_reason:
        head += f" ABORTED aborted_reason={outcome.aborted_reason}"
    print(head)
    if outcome.notes:
        print(f"  {outcome.notes}")
    print(f"  run_id={outcome.run_id} counters={json.dumps(outcome.counters)}")
    if probe_path is not None:
        print(f"  probe: {probe_path}")
    if args.notify:
        _notify(head)
    return outcome.exit_code


def _notify(message: str) -> None:
    """Opt-in one-line SMS. ⚠ A send failure must NEVER change the exit code."""
    script = Path.home() / ".claude" / "skills" / "message-brendan" / "send.sh"
    try:
        subprocess.run([str(script), message], timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("notify: send failed (ignored): %s", exc)


# ---- BF-10: the morning report ---------------------------------------------
def _cmd_subcategory_report(args: argparse.Namespace) -> int:
    """One ledger, both lanes, and the JVN-coverage reconciliation.

    ⚠ Also WRITES `data/backfill-report-<run_id>.json`, so 09:00 has an artifact
    even if the terminal is gone."""
    from job_enricher import backfill as bfl

    store = Store()
    report = bfl.build_report(store, run_id=args.run_id, kind=args.kind)
    rendered = bfl.render_report(report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(rendered)
    run_id = (
        (report.get("label") or {}).get("run_id")
        or (report.get("push") or {}).get("run_id")
        or "none"
    )
    out = store.db_path.parent / f"backfill-report-{run_id}.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"  (written to {out})")
    except OSError as exc:
        logger.warning("subcategory-report: could not write %s: %s", out, exc)
    if args.notify:
        first = rendered.splitlines()[0] if rendered else "subcategory-report"
        _notify(first)
    return 0


# ---- BF-12b: the throttled drain to JVN ------------------------------------
def _cmd_subcategory_push(args: argparse.Namespace) -> int:
    """Drain labelled subcategories to JVN, paced from `BF-16`'s measurement.

    ⚠ There is NO `--concurrency` flag and no concurrency knob. One in-flight
    request = one of the pool's 15 slots; N=1 satisfies the 2026-05-17 incident's
    invariant STRUCTURALLY and must not be traded for speed.

    ⚠ `--probe` / `--slot-hold` ARE THE SEAM BETWEEN BF-16 AND THIS COMMAND.
    Without one of them the printed sleep, rows/hour and ETA come from the
    UNMEASURED `PUSH_SLOT_HOLD_CEILING_S = 5.0` placeholder, so the runbook step
    'run the probe, fill in the table, then push' would produce an ETA unrelated
    to the measurement. `--probe` is the one the runbook uses."""
    import signal

    from job_enricher import backfill as bfl

    store = Store()
    slot_hold, t_req_p95 = args.slot_hold, None
    if args.probe:
        try:
            report = json.loads(Path(args.probe).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"subcategory-push: refused — cannot read {args.probe}: {exc}")
            return 2
        probe_hold, t_req_p95, note = bfl.slot_hold_from_probe(report, args.batch)
        if probe_hold is None:
            # ⚠ REFUSE, never fall back. A silent fallback to the placeholder is
            # precisely the defect --probe exists to close.
            print(f"subcategory-push: refused — {args.probe}: {note}")
            return 2
        print(f"subcategory-push: {note}")
        if slot_hold is None:
            slot_hold = probe_hold
    lock_path = store.db_path.parent / bfl.PUSH_LOCK_NAME
    acquired, reason = lock_mod.try_acquire(lock_path, stale_after_hours=6)
    if not acquired:
        print(f"subcategory-push: skipped — {reason}")
        return 75

    stop_path = store.db_path.parent / bfl.PUSH_STOP_SENTINEL_NAME

    def _on_signal(signum, _frame):
        logger.warning("subcategory-push: signal %s — stopping after this batch", signum)
        try:
            stop_path.touch()
        except OSError:
            pass

    previous = [
        (sig, signal.signal(sig, _on_signal))
        for sig in (signal.SIGTERM, signal.SIGINT)
    ]
    try:
        outcome = bfl.push_subcategories(
            store, limit=args.limit, batch=args.batch, duty_pct=args.duty,
            max_seconds=args.max_seconds, dry_run=args.dry_run,
            slot_hold_p95=slot_hold, t_req_p95=t_req_p95,
            stop_path=stop_path,
        )
    finally:
        for sig, handler in previous:
            signal.signal(sig, handler)
        lock_mod.release(lock_path)

    head = f"subcategory-push: status={outcome.status}"
    if outcome.aborted_reason:
        head += f" ABORTED aborted_reason={outcome.aborted_reason}"
    print(head)
    if outcome.notes:
        print(f"  {outcome.notes}")
    print(f"  run_id={outcome.run_id} counters={json.dumps(outcome.counters)}")
    print(f"  effective_sleep_at_end={outcome.effective_sleep}s")
    if args.notify:
        _notify(head)
    return outcome.exit_code


# ---- BF-16: measure the per-request write-back cost ------------------------
def _cmd_subcategory_push_probe(args: argparse.Namespace) -> int:
    """Measure T_req(B), T_ping and S(B) against PROD JVN, then DERIVE the pace.

    ⚠ RUN FROM THE PROD CHECKOUT. Each POST re-writes rows JVN already holds, so
    it is idempotent; nothing local is stamped."""
    from job_enricher import backfill as bfl
    from job_enricher.jvn_client import JVNClient

    store = Store()
    sizes = tuple(int(x) for x in str(args.sizes).split(",") if x.strip())
    client = JVNClient(timeout=bfl.PUSH_HTTP_TIMEOUT_S)
    report = bfl.push_probe(
        store, client, batches=args.batches, sizes=sizes, duty_pct=args.duty,
    )
    out = Path(args.out) if args.out else (
        store.db_path.parent
        / f"subcategory-push-probe-{now_iso().replace(':', '-')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"subcategory-push-probe: wrote {out}")
    print(
        "⚠ Record the chosen (batch, duty_pct) pair in docs/BACKFILL.md WITH the "
        "numbers that justified it, the derived rows/hour and the ETA."
    )
    return 0


# ---- BF-14: scoped subcategory rollback ------------------------------------
# ⚠ The SAME guard shape `reenrich` puts on its wide form, deliberately: the two
# dangerous commands in this repo must behave identically under muscle memory.
RESET_CONFIRM_THRESHOLD = 500

# The five contract values, so `--source all` cannot silently miss a lane. Note
# 'judge' and 'human' are reachable ONLY by naming them: `all` here means the two
# MACHINE lanes plus 'classify', never a human correction.
RESET_SOURCE_CHOICES = ("rule", "backfill", "classify", "all")
_RESET_ALL_SOURCES = ("rule", "backfill", "classify")
# ⚠ THE DEFAULT IS BOTH MACHINE LANES OF A RUN, never 'backfill' alone. A single
# backfill run writes 'rule' rows (the free title/tag pass) AND 'backfill' rows
# (the model pass) under the SAME run_id, so a default of 'backfill' would make
# the runbook's `subcategory-reset --run-id <N>` silently leave every rule-pass
# row of that run non-NULL and permanently out of `rows_needing_subcategory` —
# the rollback reporting success while doing part of the job. Matches
# `store.reset_subcategories`'s own default.
_RESET_DEFAULT_SOURCES = ("rule", "backfill")


def _cmd_subcategory_reset(args: argparse.Namespace) -> int:
    """Un-write machine-written subcategories, scoped by run / source / category.

    ⚠ THIS RESETS THE ENRICHER ONLY. Rows already drained by `subcategory-push`
    are live in JVN Postgres and this command cannot un-write them — the JVN-side
    statement is `ADM-15`. The printed already-pushed count IS the size of that
    second half of the job."""
    store = Store()
    if args.source is None:
        sources = _RESET_DEFAULT_SOURCES
    elif args.source == "all":
        sources = _RESET_ALL_SOURCES
    else:
        sources = (args.source,)
    source_label = "+".join(sources) if args.source is None else args.source
    affected, pushed = store.reset_subcategories(
        run_id=args.run_id, sources=sources, category=args.category,
        dry_run=True,
    )
    # COUNT FIRST, ALWAYS.
    print(
        f"subcategory-reset: {affected} rows match "
        f"(run_id={args.run_id} source={source_label} category={args.category})"
    )
    print(
        f"subcategory-reset: ⚠ {pushed} of them were ALREADY PUSHED to JVN. This "
        f"command cannot un-write those — run ADM-15 on the JVN side or the "
        f"rollback is only half done."
    )
    if args.dry_run:
        print("subcategory-reset: --dry-run — nothing was modified")
        return 0
    if affected > RESET_CONFIRM_THRESHOLD and not args.yes_i_mean_all:
        print(
            f"subcategory-reset: REFUSING — {affected} rows exceeds "
            f"{RESET_CONFIRM_THRESHOLD}. Re-run with --yes-i-mean-all if you "
            f"really mean it, or scope it with --run-id. Nothing was modified.",
            file=sys.stderr,
        )
        return 2
    done, _ = store.reset_subcategories(
        run_id=args.run_id, sources=sources, category=args.category,
    )
    print(f"subcategory-reset: reset {done} rows; they are back in the queue")
    return 0


# ---- unfail (P0-3: the way back from terminal 'failed') --------------------
def _cmd_unfail(args: argparse.Namespace) -> int:
    """Return terminal 'failed' rows to the queue.

    A terminal row is a JUDGEMENT, not a fact — the cause is often a transient
    engine outage. Without this, `status='failed'` is a one-way drain."""
    store = Store()
    n = store.unfail(limit=args.limit)
    print(f"unfail: returned {n} rows from terminal 'failed' to the queue")
    return 0


# ---- taxonomy parity with the JVN backend (ENR-PAR-2) ----------------------
# ENR-PAR-1 checks the enricher's own copies of the slugs against each other.
# This half compares them with what the JVN backend serves, which is how the
# old 6-vs-7 category drift would have been caught.
#
# Two halves:
#   (a) PR-blocking, NO NETWORK — tests/test_taxonomy_parity.py reads the
#       backend's generated artifact in this monorepo, src/backend/taxonomy.json.
#   (b) Scheduled, LIVE — `cli parity-check --base-url <JVN>` GETs
#       /api/jobs/facets, runs the same assertions against the live payload,
#       exits 1 on any mismatch and texts on divergence.
JVN_TAXONOMY_ARTIFACT = JVN_ROOT / "src" / "backend" / "taxonomy.json"
JVN_TAXONOMY_GENERATOR = "src/backend/tools/generate_taxonomy_artifact.py"

# The canonical table from the shared contract, sort_order 0..16. Label- and
# slug-alphabetical (for this set they coincide). parent_slug is
# `software_engineering` on every row.
#
# ⚠ `growth_engineering` (8) and `product_engineering` (12) were INSERTED, not
# appended: every slug from `infrastructure_platform` on carries a sort_order one
# or two higher than it did at 15 slugs. A JVN snapshot that merely appended the
# two new rows therefore fails on nine `sort_order` comparisons, not two.
CANONICAL_SUBCATEGORY_TABLE: list[tuple[int, str, str]] = [
    (0, "ai_engineering", "AI Engineering"),
    (1, "backend", "Backend"),
    (2, "data_engineering", "Data Engineering"),
    (3, "devops_sre", "DevOps & Site Reliability"),
    (4, "embedded_systems", "Embedded & Low-Level Systems"),
    (5, "forward_deployed", "Forward Deployed"),
    (6, "frontend", "Frontend"),
    (7, "full_stack", "Full Stack"),
    (8, "growth_engineering", "Growth Engineering"),
    (9, "infrastructure_platform", "Infrastructure & Platform"),
    (10, "ml_engineering", "Machine Learning"),
    (11, "mobile", "Mobile"),
    (12, "product_engineering", "Product Engineering"),
    (13, "qa_testing", "QA & Testing"),
    (14, "quantitative", "Quantitative & Trading Systems"),
    (15, "robotics_autonomy", "Robotics & Autonomy"),
    (16, "security", "Security"),
]


def normalize_facets_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a LIVE `/api/jobs/facets` body (camelCase FacetOption) into the
    same snake_case shape the backend's `taxonomy.json` uses, so exactly ONE
    comparison function serves both halves."""

    def opts(raw: Any) -> list[dict[str, Any]]:
        out = []
        for o in raw or []:
            if not isinstance(o, dict):
                continue
            out.append({
                "slug": o.get("slug"),
                "label": o.get("label"),
                "sort_order": o.get("sort_order", o.get("sortOrder")),
                "parent_slug": o.get("parent_slug", o.get("parentSlug")),
            })
        return out

    snap: dict[str, Any] = {
        "categories": opts(payload.get("categories")),
        "subcategories": opts(payload.get("subcategories")),
    }
    # `levels` rides along when the payload carries it, so a normalized live
    # payload has the same shape as the backend's taxonomy.json. Conditional
    # (like `subcategory_sources`) so a payload without the key is not given an
    # empty one.
    levels = payload.get("levels")
    if levels is not None:
        snap["levels"] = opts(levels)
    sources = payload.get("subcategory_sources", payload.get("subcategorySources"))
    if sources is not None:
        snap["subcategory_sources"] = sorted(sources)
    return snap


def compare_taxonomy_snapshot(
    snap: dict[str, Any], *, allow_empty_subcategories: bool = False
) -> list[str]:
    """Compare a JVN taxonomy snapshot against this repo's canonical sets.

    Returns a list of human-readable problems; EMPTY means parity. Pure — no
    network, no file I/O — so it is unit-testable against canned payloads.

    `allow_empty_subcategories` is the Phase-1 gate: before SCHEMA-7 seeds the
    17 rows JVN legitimately reports zero subcategories, and this check would
    otherwise be red for the whole Phase-1 window.
    """
    problems: list[str] = []

    cat_slugs = {c.get("slug") for c in snap.get("categories") or []}
    if cat_slugs != set(tax.CATEGORIES):
        only_jvn = sorted(x for x in cat_slugs - set(tax.CATEGORIES) if x)
        only_enr = sorted(set(tax.CATEGORIES) - cat_slugs)
        if only_jvn:
            problems.append(f"categories: JVN-only {only_jvn}")
        if only_enr:
            problems.append(f"categories: enricher-only {only_enr}")

    subs = snap.get("subcategories") or []
    sub_slugs = {s.get("slug") for s in subs}
    if not subs and allow_empty_subcategories:
        # Phase-1 window: SCHEMA-7 has not seeded the 17 rows yet, so JVN
        # legitimately reports none. Category parity is still enforced.
        logger.info(
            "parity: JVN reports zero subcategories; skipping the subcategory "
            "assertions (--allow-empty-subcategories)"
        )
        return problems

    if sub_slugs != set(tax.SUBCATEGORIES):
        only_jvn = sorted(x for x in sub_slugs - set(tax.SUBCATEGORIES) if x)
        only_enr = sorted(set(tax.SUBCATEGORIES) - sub_slugs)
        if only_jvn:
            problems.append(f"subcategories: JVN-only {only_jvn}")
        if only_enr:
            problems.append(f"subcategories: enricher-only {only_enr}")

    by_slug = {s.get("slug"): s for s in subs}
    for sort_order, slug, label in CANONICAL_SUBCATEGORY_TABLE:
        row = by_slug.get(slug)
        if row is None:
            continue  # already reported as enricher-only above
        if row.get("label") != label:
            problems.append(f"{slug}: label {row.get('label')!r} != {label!r}")
        if row.get("sort_order") is not None and row["sort_order"] != sort_order:
            problems.append(f"{slug}: sort_order {row['sort_order']} != {sort_order}")
        if row.get("parent_slug") != tax.SUBCATEGORY_PARENT:
            problems.append(
                f"{slug}: parent_slug {row.get('parent_slug')!r} != "
                f"{tax.SUBCATEGORY_PARENT!r}"
            )

    if "subcategory_sources" in snap:
        if sorted(snap["subcategory_sources"]) != sorted(tax.SUBCATEGORY_SOURCES):
            problems.append(
                f"subcategory_sources: {sorted(snap['subcategory_sources'])} != "
                f"{sorted(tax.SUBCATEGORY_SOURCES)}"
            )
    return problems


def _text_brendan(message: str) -> None:
    """Best-effort SMS on divergence — the same channel the existing
    com.bp.jvn-health-watch launchd job uses. The drift this catches is slow,
    silent and only observable in production, so a scheduled job that TEXTS is
    the right shape; a log line nobody reads is not."""
    send = Path.home() / ".claude" / "skills" / "message-brendan" / "send.sh"
    if not send.exists():
        logger.warning("parity-check: %s not found; no text sent", send)
        return
    try:
        proc = subprocess.run(
            [str(send), message], check=False, timeout=60,
            capture_output=True, text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("parity-check: could not text: %s", exc)
        return
    # ⚠ THE RESULT IS NOT DISCARDED. `check=False` plus an ignored return code
    # meant a FAILED alarm was completely silent — no exception, no log line —
    # on the one channel whose whole justification (above) is that a log line
    # nobody reads is the wrong shape. If the text did not go out, that has to
    # be the loudest thing in the run.
    if proc.returncode != 0:
        logger.error(
            "parity-check: THE DIVERGENCE TEXT DID NOT SEND — %s exited %d "
            "(stderr: %s); the taxonomy alarm reached nobody",
            send, proc.returncode, (proc.stderr or "").strip()[:500] or "<empty>",
        )


def _cmd_parity_check(args: argparse.Namespace) -> int:
    """GET the live /api/jobs/facets and assert parity."""
    import httpx

    if args.write_snapshot:
        # There is no vendored snapshot any more: the offline half reads the
        # backend's own artifact in this monorepo. The flag stays accepted so a
        # stale caller gets this message, not an argparse usage error.
        print(
            "parity-check: --write-snapshot is retired. The snapshot is JVN's "
            f"generated {JVN_TAXONOMY_ARTIFACT.relative_to(JVN_ROOT)}; regenerate "
            f"it with {JVN_TAXONOMY_GENERATOR}.",
            file=sys.stderr,
        )
        return 2

    url = f"{args.base_url.rstrip('/')}/api/jobs/facets"
    try:
        resp = httpx.get(url, timeout=args.timeout)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"parity-check: could not read {url}: {exc}", file=sys.stderr)
        return 1

    snap = normalize_facets_payload(payload)
    problems = compare_taxonomy_snapshot(
        snap, allow_empty_subcategories=args.allow_empty_subcategories
    )
    n_sub = len(snap.get("subcategories") or [])
    n_cat = len(snap.get("categories") or [])
    print(
        f"subcategories: {n_sub}/{len(tax.SUBCATEGORIES)} match, "
        f"categories: {n_cat}/{len(tax.CATEGORIES)} match"
        if not problems
        else f"parity-check: {len(problems)} problem(s) against {url}"
    )
    sys.stdout.flush()  # keep the summary above the problems in a combined log
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)

    if problems:
        if args.text_on_divergence:
            _text_brendan(
                "JVN taxonomy parity FAILED: " + "; ".join(problems[:3])
            )
        return 1
    return 0


# ---- parser ----------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="job_enricher.cli", description="Job-enricher pipeline CLI.")
    subs = p.add_subparsers(dest="command", metavar="command")

    subs.add_parser("init", help="create the SQLite schema").set_defaults(func=_cmd_init)

    subs.add_parser("tick-acquire", help="acquire lock + open tick (exit 75 if held)").set_defaults(
        func=_cmd_tick_acquire
    )
    pe = subs.add_parser("tick-end", help="close tick + release lock")
    pe.add_argument("--status", default="ok", choices=["ok", "error"])
    pe.add_argument("--notes", default=None)
    pe.add_argument(
        "--tick-id", type=int, default=None,
        help="refuse unless this matches meta current_tick_id (stray tick-end "
             "guard; also read from ENRICH_TICK_ID)",
    )
    pe.set_defaults(func=_cmd_tick_end)

    subs.add_parser("taxonomy-version", help="print taxonomy version hash").set_defaults(
        func=_cmd_taxonomy_version
    )
    subs.add_parser("enrich-config", help="print runtime knobs as JSON").set_defaults(
        func=_cmd_enrich_config
    )

    # knob setters
    for name, knob, setter, typ in [
        ("set-classify-engine", "classify:engine", ec.set_classify_engine, str),
        ("set-classify-model", "classify:model", ec.set_classify_model, str),
        ("set-classify-batch", "classify:batch_size", ec.set_classify_batch_size, int),
        ("set-classify-fanout", "classify:fan_out", ec.set_classify_fan_out, int),
        ("set-judge-engine", "judge:engine", ec.set_judge_engine, str),
        ("set-judge-model", "judge:model", ec.set_judge_model, str),
        ("set-judge-floor", "judge:human_floor", ec.set_judge_human_floor, float),
        ("set-judge-scope", "judge:scope", ec.set_judge_scope, str),
        ("set-judge-ceiling", "judge:confidence_ceiling", ec.set_judge_confidence_ceiling, float),
        ("set-opencode-model", "opencode:model", ec.set_opencode_model, str),
        ("set-enrich-per-tick-limit", "enrich:per_tick_limit", ec.set_enrich_per_tick_limit, int),
        ("set-backfill-batch", "backfill:batch_size", ec.set_backfill_batch_size, int),
        ("set-backfill-max-attempts", "backfill:max_attempts", ec.set_backfill_max_attempts, int),
    ]:
        sp = subs.add_parser(name, help=f"set {knob}")
        sp.add_argument("value", type=typ)
        sp.set_defaults(func=_cmd_set_knob, knob=knob, setter=setter)

    jsc = subs.add_parser(
        "judge-subcategory-corrections",
        help="allow/forbid the judge to correct subcategories (default on)",
    )
    jsc.add_argument("value", choices=["on", "off"])
    jsc.set_defaults(
        func=_cmd_set_knob, knob="judge:subcategory_corrections",
        setter=lambda s, v: ec.set_judge_subcategory_corrections(s, v == "on"),
    )

    wbs = subs.add_parser(
        "writeback-send-subcategories",
        help="ship subcategories to JVN on /results (default OFF — flip ON only "
             "after JVN has SCHEMA-4)",
    )
    wbs.add_argument("value", choices=["on", "off"])
    wbs.set_defaults(
        func=_cmd_set_knob, knob="writeback:send_subcategories",
        setter=lambda s, v: ec.set_writeback_send_subcategories(s, v == "on"),
    )

    jt = subs.add_parser("judge-toggle", help="turn the judge on/off")
    jt.add_argument("value", choices=["on", "off"])
    jt.set_defaults(func=_cmd_set_knob, knob="judge:enabled",
                    setter=lambda s, v: ec.set_judge_enabled(s, v == "on"))

    rk = subs.add_parser(
        "reset-knob",
        help="clear a runtime knob so it follows the committed default",
    )
    rk.add_argument("knob", choices=sorted(ec.KNOB_META_KEYS))
    rk.set_defaults(func=_cmd_reset_knob)

    pp = subs.add_parser("pull", help="claim a batch of unenriched jobs from JVN")
    pp.add_argument("--limit", type=int, default=None)
    pp.set_defaults(func=_cmd_pull)

    pc = subs.add_parser("clean", help="Stage A: deterministic description cleaning")
    pc.add_argument("--limit", type=int, default=None)
    pc.set_defaults(func=_cmd_clean)

    cq = subs.add_parser(
        "classify-queue",
        help="write jobs needing classification to data/chunks/classify-*.json "
             "files (classify:batch_size per file); emit a [{chunk_file, count}] "
             "manifest",
    )
    cq.add_argument("--limit", type=int, default=None)
    cq.set_defaults(func=_cmd_classify_queue)

    re_ = subs.add_parser("record-enrichment", help="record classify results (JSON array)")
    re_.add_argument("--json", default=None)
    re_.add_argument("--json-file", default=None)
    re_.set_defaults(func=_cmd_record_enrichment)

    cr = subs.add_parser(
        "classify-run",
        help="run classify IN-PROCESS via the classify:engine (ollama/opencode/"
             "claude-code) over the classify-*.json chunks + record results",
    )
    cr.add_argument("--engine", default=None, choices=list(ec.ENGINE_CHOICES),
                    help="override the classify:engine knob for this run")
    cr.add_argument("--chunk-file", default=None, help="run one chunk file (default: all)")
    cr.set_defaults(func=_cmd_classify_run)

    jq = subs.add_parser(
        "judge-queue",
        help="write enrichments needing judging to data/chunks/judge-*.json "
             "files (classify:batch_size per file); emit a [{chunk_file, count}] "
             "manifest",
    )
    jq.add_argument("--limit", type=int, default=None)
    jq.set_defaults(func=_cmd_judge_queue)

    rj = subs.add_parser("record-judge", help="apply judge verdicts (JSON array)")
    rj.add_argument("--json", default=None)
    rj.add_argument("--json-file", default=None)
    rj.set_defaults(func=_cmd_record_judge)

    jr = subs.add_parser(
        "judge-run",
        help="run judge IN-PROCESS via the judge:engine over the judge-*.json "
             "chunks + record verdicts",
    )
    jr.add_argument("--engine", default=None, choices=list(ec.ENGINE_CHOICES),
                    help="override the judge:engine knob for this run")
    jr.add_argument("--chunk-file", default=None, help="run one chunk file (default: all)")
    jr.set_defaults(func=_cmd_judge_run)

    subs.add_parser("write-back", help="Stage D: durable write-back to JVN").set_defaults(
        func=_cmd_write_back
    )

    subs.add_parser("health", help="observability JSON").set_defaults(func=_cmd_health)
    subs.add_parser("status", help="alias for health").set_defaults(func=_cmd_status)
    subs.add_parser("serve", help="run the optional inbound edge").set_defaults(func=_cmd_serve)

    pd = subs.add_parser("dashboard", help="run the local read+edit dashboard (127.0.0.1)")
    pd.add_argument("--port", type=int, default=None, help="override DASHBOARD_PORT")
    pd.add_argument("--host", default="127.0.0.1")
    pd.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit a non-loopback --host (exposes the unauthenticated knob "
             "editor beyond localhost; never tunnel it). Without this a "
             "non-loopback --host is refused.",
    )
    pd.add_argument(
        "--api-only",
        action="store_true",
        help="serve the JSON API only (pair with `npm run dev` on :5173)",
    )
    pd.set_defaults(func=_cmd_dashboard)

    bg = subs.add_parser("build-golden-set", help="sample JVN into golden/seed")
    bg.add_argument("--n", type=int, default=150)
    bg.set_defaults(func=_cmd_build_golden)

    ev = subs.add_parser("eval", help="score against the golden set")
    ev.add_argument("--set", default="golden")
    ev.add_argument("--judge", default=None, choices=["on", "off"])
    ev.add_argument("--gate", action="store_true")
    ev.add_argument("--baseline", default=None)
    ev.add_argument(
        "--allow-draft", action="store_true",
        help="score against draft labels too — ADVISORY ONLY (never gates, always exits 0)",
    )
    ev.add_argument(
        "--engine", default=None,
        help="score the per-engine predictions.<engine>.json (from `eval-run`)",
    )
    ev.add_argument(
        "--tag", default=None,
        help="namespace the prediction + scorecard artifacts (predictions.<tag>.<engine>[.judge_off].json). REQUIRED for a taxonomy A/B: without it the v7 run OVERWRITES the v6 artifact",
    )
    ev.add_argument(
        "--facet", default="all", choices=["all", "subcategory"],
        help="'subcategory' scores the SUBCATEGORY pool and writes "
             "scorecard.subcategory[.tag][.engine].json — it never touches "
             "scorecard.json, which is the file metrics-push ships to JVN",
    )
    ev.add_argument(
        "--gate-group", action="append", default=None,
        choices=["category", "subcategory"],
        help="repeatable. Each group gates on its OWN denominator and min-n; "
             "one group refusing does not suppress the others",
    )
    ev.add_argument(
        "--model", default=None,
        help="the model under test, for the subcategory gate's independence "
             "rail (it refuses when the pre-labeller equals it). REQUIRED for "
             "any --gate run covering the subcategory group on a pre-labelled "
             "pool: without it the model under test is unknown and the gate "
             "refuses rather than passing on an unchecked rail",
    )
    ev.add_argument(
        "--conf-threshold", type=float, default=0.80,
        help="calibration split point. DEFAULT 0.80 for comparability with "
             "every committed baseline; the 0.85 production ceiling is "
             "reported separately as calibration_error_rate_below_at_ceiling",
    )
    ev.add_argument(
        "--reasoning", action="store_true",
        help="also print the per-row 'why' (predicted vs gold + classify/judge rationale)",
    )
    ev.set_defaults(func=_cmd_eval)

    er = subs.add_parser(
        "eval-run",
        help="headlessly generate per-engine golden predictions (classify [+judge]) "
             "with per-item latency + reasoning, for `cli eval --engine <e>`",
    )
    er.add_argument("--engine", required=True, choices=list(ec.ENGINE_CHOICES))
    er.add_argument("--set", default="golden")
    er.add_argument("--judge", default=None, choices=["on", "off"],
                    help="off = classify only; default runs the judge too")
    er.add_argument("--batch", type=int, default=1,
                    help="jobs per model call (1 = exact per-item latency; higher = faster)")
    er.add_argument("--limit", type=int, default=None, help="first N golden rows")
    er.add_argument("--human-only", action="store_true",
                    help="only generate predictions for label_source='human' rows")
    er.add_argument("--classify-model", default=None,
                    help="override classify model/tier (default: knob for claude-code, else opencode:model)")
    er.add_argument("--judge-model", default=None, help="override judge model/tier")
    er.add_argument(
        "--prompt", default="classify", choices=["classify", "backfill"],
        help="'backfill' runs the SUBCATEGORY-ONLY lane (title + company tags, "
             "NO description) through the SAME build_subcategory_prompt "
             "production uses — the lane the classify-only gate never measures",
    )
    er.add_argument(
        "--tag", default=None,
        help="namespace the prediction + scorecard artifacts (predictions.<tag>.<engine>[.judge_off].json). REQUIRED for a taxonomy A/B: without it the v7 run OVERWRITES the v6 artifact",
    )
    er.set_defaults(func=_cmd_eval_run)

    pl = subs.add_parser(
        "prelabel",
        help="pre-label a drawn golden pool with an INDEPENDENT model, for "
             "human review (facet: category or subcategory)",
    )
    pl.add_argument("--facet", required=True, choices=["category", "subcategory"])
    pl.add_argument("--engine", required=True, choices=list(ec.ENGINE_CHOICES))
    pl.add_argument("--model", required=True)
    pl.add_argument(
        "--under-test", required=True,
        help="the '<engine>:<model>' being evaluated. REQUIRED: the command "
             "REFUSES (exit 2) when the pre-labeller equals it — a model "
             "agreeing with itself is self-consistency, not evidence",
    )
    pl.add_argument("--seed", type=int, default=PARAM_DRAW_SEED)
    pl.add_argument("--draw", type=int, default=None,
                    help="draw N rows (seeded + stratified); default = the whole pool")
    pl.add_argument("--batch", type=int, default=5)
    pl.add_argument("--out", default=None)
    pl.set_defaults(func=_cmd_prelabel)

    rb = subs.add_parser(
        "review-build",
        help="turn a prelabel artifact into a tiered human worklist plus a "
             "seeded, stratified audit sample",
    )
    rb.add_argument("--facet", required=True, choices=["category", "subcategory"])
    rb.add_argument("--audit-rate", type=float, default=None,
                    help="default 1.0 for category (the corroborator is NOT "
                         "independent, so every drawn row is human-decided) "
                         "and 0.15 for subcategory")
    rb.add_argument("--seed", type=int, default=PARAM_DRAW_SEED)
    rb.add_argument("--prelabel-file", default=None)
    rb.add_argument("--out", default=None)
    rb.set_defaults(func=_cmd_review_build)

    rr = subs.add_parser(
        "review-render",
        help="render a review worklist as one self-contained static HTML page",
    )
    rr.add_argument("--facet", required=True, choices=["category", "subcategory"])
    rr.add_argument("--review-file", default=None)
    rr.add_argument("--out", default=None)
    rr.set_defaults(func=_cmd_review_render)

    ra = subs.add_parser(
        "review-apply",
        help="fold a REVIEWED worklist into golden/seed, write the audit "
             "verdict, and enforce the promotion switch",
    )
    ra.add_argument("--facet", required=True, choices=["category", "subcategory"])
    ra.add_argument(
        "--threshold", type=float, default=derive_audit_max(PARAM_PRELABEL_ERROR_RATE),
        help="PARAM_AUDIT_MAX — DERIVED from EV-2b's measured "
             "PARAM_PRELABEL_ERROR_RATE, not invented. Defaults to the "
             "conservative floor (0.05) while that measurement does not exist",
    )
    ra.add_argument("--review-file", default=None)
    ra.set_defaults(func=_cmd_review_apply)

    wb = subs.add_parser(
        "subcategory-weak-baseline",
        help="run the deterministic title labeler over the gold-SWE pool and "
             "score it — the G2 baseline. ⚠ NEEDS a scored subcategory gold "
             "pool: with an empty pool the card is an all-zeros placeholder "
             "and the command exits 2",
    )
    wb.add_argument(
        "--allow-empty-pool", action="store_true",
        help="write the placeholder card anyway and exit 0 — the prediction "
             "artifact is still durable, but the card CANNOT gate",
    )
    wb.set_defaults(func=_cmd_subcategory_weak_baseline)

    rn = subs.add_parser(
        "reenrich",
        help="manually re-queue rows whose taxonomy version is strictly below "
             "v<N>+<hash> (smaller declared N; same-N different-hash is NOT below)",
    )
    rn.add_argument("--taxonomy-below", required=True)
    rn.add_argument(
        "--dry-run", action="store_true",
        help="print the matched count and exit WITHOUT modifying anything",
    )
    rn.add_argument(
        "--yes-i-mean-all", action="store_true",
        help=f"required to proceed when more than {REENRICH_CONFIRM_THRESHOLD} "
             f"rows match (same flag name as subcategory-reset)",
    )
    rn.add_argument(
        "--limit", type=int, default=None,
        help="reset at most this many matched rows",
    )
    rn.set_defaults(func=_cmd_reenrich)

    ssi = subs.add_parser(
        "subcategory-scope-import",
        help="import the OPEN-SWE backfill scope exported from JVN's Postgres "
             "(NDJSON; idempotent on the composite key)",
    )
    ssi.add_argument("--json-file", required=True)
    ssi.set_defaults(func=_cmd_subcategory_scope_import)

    sbf = subs.add_parser(
        "subcategory-backfill",
        help="Tier-2: label the SWE backlog's subcategories, off the live lane "
             "(own .backfill.lock; exit 75 if held)",
        description="⚠ There is deliberately NO --concurrency flag: "
                    "_call_with_repair is strictly sequential, ChunkEngine has "
                    "no parallel path, and a threadpool would multiply SQLite "
                    "write contention against the live tick. The levers for "
                    "wall time are --batch and the model tier.",
    )
    sbf.add_argument("--until", default=None,
                     help="absolute local wall-clock stop time, e.g. 09:00")
    sbf.add_argument("--tz", default="America/Chicago")
    sbf.add_argument("--max-seconds", type=int, default=None)
    sbf.add_argument("--limit", type=int, default=None)
    sbf.add_argument("--batch", type=int, default=None)
    sbf.add_argument("--model", default=None, choices=["haiku", "sonnet", "opus"])
    sbf.add_argument("--open-only", action="store_true")
    sbf.add_argument("--dry-run", action="store_true",
                     help="run the FULL pipeline and write NOTHING; emit a probe JSON")
    sbf.add_argument("--probe-json", default=None)
    sbf.add_argument("--notify", action="store_true")
    sbf.set_defaults(func=_cmd_subcategory_backfill)

    sbe = subs.add_parser(
        "set-backfill-enabled",
        help="arm/disarm the Tier-2 backfill lane (default OFF — ships dark)",
    )
    sbe.add_argument("value", choices=["on", "off"])
    sbe.set_defaults(
        func=_cmd_set_knob, knob="backfill:enabled",
        setter=lambda s, v: ec.set_backfill_enabled(s, v == "on"),
    )

    sre = subs.add_parser(
        "subcategory-reset",
        help="un-write machine-written subcategories, scoped by run/source/"
             "category (never touches judge or human rows)",
    )
    sre.add_argument("--run-id", type=int, default=None)
    sre.add_argument(
        "--source", choices=list(RESET_SOURCE_CHOICES), default=None,
        help="default: both machine lanes of a run (rule+backfill) — ⚠ a run "
             "writes BOTH, so scoping to 'backfill' alone leaves its rule-pass "
             "rows labelled; 'all' adds the live 'classify' lane. 'judge' and "
             "'human' are unreachable by design.",
    )
    sre.add_argument("--category", default=None)
    sre.add_argument("--dry-run", action="store_true")
    sre.add_argument(
        "--yes-i-mean-all", action="store_true",
        help=f"required above {RESET_CONFIRM_THRESHOLD} affected rows",
    )
    sre.set_defaults(func=_cmd_subcategory_reset)

    spp = subs.add_parser(
        "subcategory-push-probe",
        help="measure T_req/T_ping/S(B) against prod JVN and DERIVE the drain "
             "pace (a measurement, not a push)",
    )
    spp.add_argument("--batches", type=int, default=3)
    spp.add_argument("--sizes", default="50,100,250,500")
    spp.add_argument("--duty", type=int, default=25)
    spp.add_argument("--out", default=None)
    spp.set_defaults(func=_cmd_subcategory_push_probe)

    spu = subs.add_parser(
        "subcategory-push",
        help="drain labelled subcategories to JVN, paced (own "
             ".subcategory-push.lock; exit 75 if held; exit 2 when "
             "writeback:send_subcategories is off)",
        description="⚠ No --concurrency flag and no concurrency knob: one "
                    "in-flight request = one of the pool's 15 slots. See "
                    "docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md.",
    )
    spu.add_argument("--limit", type=int, default=None)
    spu.add_argument("--batch", type=int, default=None)
    spu.add_argument("--duty", type=int, default=None)
    spu.add_argument("--max-seconds", type=int, default=None)
    spu.add_argument(
        "--probe", default=None,
        help="BF-16's subcategory-push-probe-*.json — the MEASURED S_p95 the "
             "sleep, rows/hour and ETA are derived from. Without it (or "
             "--slot-hold) they come from the UNMEASURED 5.0s placeholder and "
             "the command says so, loudly.",
    )
    spu.add_argument(
        "--slot-hold", type=float, default=None,
        help="measured S_p95 in seconds, when you have the number but not the "
             "probe file; overrides --probe's cell",
    )
    spu.add_argument("--dry-run", action="store_true")
    spu.add_argument("--notify", action="store_true")
    spu.set_defaults(func=_cmd_subcategory_push)

    srp = subs.add_parser(
        "subcategory-report",
        help="the morning report: both lanes off one ledger, plus the "
             "JVN-coverage reconciliation",
    )
    srp.add_argument("--run-id", type=int, default=None)
    srp.add_argument("--kind", choices=["label", "push"], default=None)
    srp.add_argument("--json", action="store_true")
    srp.add_argument("--notify", action="store_true")
    srp.set_defaults(func=_cmd_subcategory_report)

    for name, knob, setter, typ in [
        ("set-push-batch", "writeback:subcategory_push_batch",
         ec.set_subcategory_push_batch, int),
        ("set-push-duty", "writeback:subcategory_push_duty_pct",
         ec.set_subcategory_push_duty_pct, int),
        ("set-push-max-seconds", "writeback:subcategory_push_max_seconds",
         ec.set_subcategory_push_max_seconds, int),
    ]:
        sp = subs.add_parser(name, help=f"set {knob}")
        sp.add_argument("value", type=typ)
        sp.set_defaults(func=_cmd_set_knob, knob=knob, setter=setter)

    uf = subs.add_parser(
        "unfail",
        help="return terminal 'failed' inbox rows to the queue (attempts reset to 0)",
    )
    uf.add_argument("--limit", type=int, default=None)
    uf.set_defaults(func=_cmd_unfail)

    pc = subs.add_parser(
        "parity-check",
        help="compare JVN's live /api/jobs/facets against this repo's taxonomy "
             "(exit 1 on any mismatch)",
    )
    pc.add_argument("--base-url", required=True)
    pc.add_argument("--timeout", type=float, default=30.0)
    pc.add_argument(
        "--allow-empty-subcategories", action="store_true",
        help="tolerate JVN reporting zero subcategories (expected until "
             "SCHEMA-7 seeds the 17 rows)",
    )
    pc.add_argument("--write-snapshot", action="store_true",
                    help="retired: exits 2 (the snapshot is the backend's "
                         "src/backend/taxonomy.json)")
    pc.add_argument("--text-on-divergence", action="store_true",
                    help="send an SMS via the message-brendan skill on mismatch")
    pc.set_defaults(func=_cmd_parity_check)

    gm = subs.add_parser(
        "golden-merge",
        help="pull JVN admin corrections into golden/seed as label_source='human'",
    )
    gm.add_argument("--since", default=None, help="ISO timestamp lower bound")
    gm.add_argument("--limit", type=int, default=None)
    gm.add_argument(
        "--allow-pre-v7", action="store_true",
        help="downgrade the v7 contract violation (corrections missing "
             "subcategories/taxonomy_version) from exit 2 to a printed "
             "warning — for a deliberate category-only merge before ADM-5 ships",
    )
    gm.set_defaults(func=_cmd_golden_merge)

    mp = subs.add_parser(
        "metrics-push",
        help="POST the latest (or given) tick's metrics to JVN (best-effort)",
    )
    mp.add_argument("--tick-id", type=int, default=None)
    mp.add_argument(
        "--strict", action="store_true",
        help="exit 2 on failure instead of the default best-effort exit 0",
    )
    mp.set_defaults(func=_cmd_metrics_push)

    return p


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        return int(func(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
