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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_enricher import enrich_config as ec
from job_enricher import lock as lock_mod
from job_enricher import taxonomy as tax
from job_enricher.clean import clean_description, truncate_for_agent
from job_enricher.store import (
    HEARTBEAT_KEY,
    LAST_SCORECARD_HASH_KEY,
    Store,
    now_iso,
)

logger = logging.getLogger(__name__)


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
    from job_enricher.metrics import drift_suspected

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

    tick_id = store.end_tick(status=status, notes=notes)
    lock_mod.release(
        store.db_path.parent / ".tick.lock",
        owner_pid=_env_int("ENRICH_LOCK_OWNER_PID"),
    )
    print(f"tick-end: closed tick_id={tick_id} status={status}")
    return 0


# ---- knobs -----------------------------------------------------------------
def _cmd_taxonomy_version(args: argparse.Namespace) -> int:
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
    inserted, skipped, received = _do_pull(store, JVNClient(), args.limit)
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
def _cmd_classify_queue(args: argparse.Namespace) -> int:
    store = Store()
    rows = store.jobs_needing_classify(limit=args.limit)
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
    engine = ec.get_classify_engine(store)
    batch = 1 if engine != "claude-code" else ec.get_classify_batch_size(store)
    manifest = _write_queue_chunks(store, out, "classify", batch)
    print(json.dumps(manifest))
    return 0


def _coerce_json_field(value: Any) -> str:
    return json.dumps(value if value is not None else [])


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
    ``{"recorded", "needs_human", "skipped", "skipped_unknown", "nulled_facets"}``.

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
    Never raises on bad data."""
    sources_by_id = store.inbox_sources_by_id(
        [i.get("job_listing_id") for i in items if isinstance(i, dict) and i.get("job_listing_id")]
    )
    recorded = 0
    needs_human_n = 0
    skipped = 0
    skipped_unknown = 0
    nulled = 0
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
        needs_human = False
        if bad:
            needs_human = True
            nulled += 1
            for facet, value in bad:
                logger.warning(
                    "record-enrichment: job_listing_id=%s has invalid %s=%r (not in taxonomy); "
                    "nulled + flagged needs_human", jid, facet, value,
                )
        store.record_enrichment(
            {
                "job_listing_id": jid,
                "source_id": source_id,
                "category": category,
                "level": level,
                "level_includes": _coerce_json_field(item.get("level_includes")),
                "tags": _coerce_json_field(item.get("tags")),
                "locations": _coerce_json_field(item.get("locations")),
                "classify_confidence": item.get("confidence"),
                "classify_reasoning": item.get("reasoning"),
                "classify_latency_ms": item.get("classify_latency_ms"),
                "taxonomy_version": version,
                "needs_human": needs_human,
                "classify_model": classify_model,
            }
        )
        recorded += 1
        needs_human_n += 1 if needs_human else 0
    return {
        "recorded": recorded,
        "needs_human": needs_human_n,
        "skipped": skipped,
        "skipped_unknown": skipped_unknown,
        "nulled_facets": nulled,
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
        f"skipped={res['skipped']} skipped_unknown={res['skipped_unknown']} "
        f"nulled_facets={res['nulled_facets']}"
    )
    return 0


# ---- judge queue + record (Stage C) ---------------------------------------
def _needs_judge(e: Any, ceiling: float) -> bool:
    """scope=low_confidence routing: judge only the rows where judging has a
    measurable payoff — classify was unsure (confidence below the ceiling, or
    missing), a facet was nulled at ingest (invalid slug), or the row is
    already flagged needs_human. Confident rows ship as-is: the measured lift
    of judging them was negative (level churn away from gold)."""
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
    enr = store.enriched_unjudged(limit=args.limit)
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
                    "level_includes": json.loads(e["level_includes"] or "[]"),
                    "tags": json.loads(e["tags"] or "[]"),
                    "locations": json.loads(e["locations"] or "[]"),
                    "confidence": e["classify_confidence"],
                },
            }
        )
    engine = ec.get_judge_engine(store)
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
        merged = _merge_judge(base, item, floor)
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
    totals = {"recorded": 0, "needs_human": 0, "skipped": 0, "skipped_unknown": 0, "nulled_facets": 0}
    for cf in chunk_files:
        try:
            jobs = json.loads(Path(cf).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("classify-run: unreadable chunk %s: %s", cf, exc)
            continue
        try:
            items = engine.classify(jobs)
        except EngineError as exc:
            logger.error("classify-run: %s failed on %s: %s", engine.name, cf, exc)
            continue
        res = record_enrichment_items(store, items, version, classify_model=model)
        for k in totals:
            totals[k] += res.get(k, 0)
    store.bump_tick_counters(
        classified=totals["recorded"], needs_human=totals["needs_human"],
        nulled_facets=totals["nulled_facets"],
    )
    _record_llm_stage_timing(store, "classify", totals["recorded"])
    print(
        f"classify-run: engine={engine_kind} model={model} "
        f"recorded={totals['recorded']} needs_human={totals['needs_human']} "
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
    for cf in chunk_files:
        try:
            items = json.loads(Path(cf).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("judge-run: unreadable chunk %s: %s", cf, exc)
            continue
        try:
            verdicts = engine.judge(items)
        except EngineError as exc:
            logger.error("judge-run: %s failed on %s: %s", engine.name, cf, exc)
            continue
        res = apply_judge_verdicts(store, verdicts, floor, judge_model=model)
        for k in totals:
            totals[k] += res.get(k, 0)
    store.bump_tick_counters(
        judged=totals["judged"], corrected=totals["corrected"],
        needs_human=totals["needs_human"],
    )
    _record_llm_stage_timing(store, "judge", totals["judged"])
    print(
        f"judge-run: engine={engine_kind} model={model} judged={totals['judged']} "
        f"corrected={totals['corrected']} needs_human={totals['needs_human']} "
        f"skipped={totals['skipped']} rejected_corrections={totals['rejected_corrections']} "
        f"chunks={len(chunk_files)}"
    )
    return 0


# ---- eval-run (headless per-engine prediction generator) -------------------
def _eval_classify_pred(item: dict[str, Any], clean_desc: str) -> dict[str, Any]:
    """A classify prediction row (the judge-off artifact)."""
    return {
        "job_listing_id": item.get("job_listing_id"),
        "source_id": item.get("source_id"),
        "category": item.get("category"),
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
        "needs_human": False,
    }
    merged = _merge_judge(base, verdict, floor)
    return {
        "job_listing_id": cp["job_listing_id"],
        "source_id": cp.get("source_id"),
        "category": merged["category"],
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
    off_path = _predictions_path("off", engine_kind)
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
    on_path = _predictions_path(None, engine_kind)
    on_path.write_text(json.dumps(judged, indent=2), encoding="utf-8")
    print(f"eval-run: wrote {len(judged)} judged predictions -> {on_path.name}")
    return 0


# the judge may only change level (outside the new_grad/entry equivalence)
# when its OWN confidence clears this bar — enforced in code, not just prompt
JUDGE_LEVEL_CONFIDENCE_MIN = 0.8
_LEVEL_EQUIVALENCE = frozenset({"new_grad", "entry"})


def _merge_judge(base: dict[str, Any], verdict: dict[str, Any], floor: float) -> dict[str, Any]:
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
    Rejected corrections are counted in the returned dict's
    ``rejected_corrections`` key (popped by the caller — not persisted)."""
    corr = dict(verdict.get("corrections") or {})
    proposed_any = bool(corr)
    passed = bool(verdict.get("passed", verdict.get("judge_pass", True)))
    conf = verdict.get("confidence", verdict.get("judge_confidence"))
    notes = verdict.get("notes", verdict.get("judge_notes"))
    reasoning = verdict.get("reasoning", verdict.get("judge_reasoning"))
    judge_latency_ms = verdict.get("judge_latency_ms")

    rejected_notes: list[str] = []
    force_needs_human = False
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
    with store.connect() as conn:
        inbox = dict(
            (r["status"], r["n"])
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM inbox GROUP BY status"
            ).fetchall()
        )
        # unsent mirrors what write-back will actually offer: terminal
        # 'failed' (poison) rows are excluded here and surfaced separately
        # via inbox['failed'] + the failed_rows key.
        unsent = conn.execute(
            "SELECT COUNT(*) AS n FROM enrichments e JOIN inbox i "
            "ON i.source_id = e.source_id AND i.job_listing_id = e.job_listing_id "
            "WHERE e.sent_at IS NULL AND i.status != 'failed'"
        ).fetchone()["n"]
        needs_human = conn.execute(
            "SELECT COUNT(*) AS n FROM enrichments WHERE needs_human = 1"
        ).fetchone()["n"]
        timings = [
            dict(r)
            for r in conn.execute(
                "SELECT stage, COUNT(*) AS runs, AVG(duration_ms) AS avg_ms, "
                "SUM(item_count) AS items, SUM(retry_count) AS retries "
                "FROM stage_timings GROUP BY stage"
            ).fetchall()
        ]
    hb = store.get_meta(HEARTBEAT_KEY)
    hb_age = None
    if hb:
        try:
            hb_age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds()
        except ValueError:
            hb_age = None
    print(
        json.dumps(
            {
                "inbox": inbox,
                "unsent": unsent,
                "needs_human": needs_human,
                "failed_rows": inbox.get("failed", 0),
                "last_heartbeat_at": hb,
                "last_heartbeat_age_s": hb_age,
                "stage_timings": timings,
                "classify_model": ec.get_classify_model(store),
                "judge_model": ec.get_judge_model(store),
                "latest_tick": store.latest_tick(),
            }
        )
    )
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
    )
    return code


# ---- reenrich (MANUAL taxonomy re-processing) -----------------------------
_TAXONOMY_VERSION_RE = re.compile(r"^v(\d+)\+(\S+)$")


def _cmd_reenrich(args: argparse.Namespace) -> int:
    """Re-queue rows whose taxonomy_version is strictly BELOW the given
    'v<N>+<hash>' (smaller declared N). Rows at the same N with a different
    hash are NOT below (hashes are unordered) — they are warned and left
    alone. Unversioned rows count as below."""
    if _TAXONOMY_VERSION_RE.match(args.taxonomy_below) is None:
        print(
            f"reenrich: --taxonomy-below must look like 'v<N>+<hash>' "
            f"(e.g. v2+3f9a1c2b8e04), got {args.taxonomy_below!r}",
            file=sys.stderr,
        )
        return 2
    store = Store()
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT job_listing_id, source_id, taxonomy_version FROM enrichments"
        ).fetchall()
        target = 0
        for r in rows:
            if _version_below(r["taxonomy_version"], args.taxonomy_below):
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
    versioning and counts as below."""
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
    into real ground truth for the regression gate."""
    from job_enricher.eval.golden import merge_corrections
    from job_enricher.jvn_client import JVNClient

    corrections = JVNClient().get_corrections(since=args.since, limit=args.limit)
    report = merge_corrections(corrections)
    print(
        f"golden-merge: matched={report['matched']} upgraded={report['upgraded']} "
        f"unmatched={report['unmatched']}"
    )
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
    the Vite dev server on :5173 for front-end iteration)."""
    import uvicorn

    from job_enricher.config import settings

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
    ]:
        sp = subs.add_parser(name, help=f"set {knob}")
        sp.add_argument("value", type=typ)
        sp.set_defaults(func=_cmd_set_knob, knob=knob, setter=setter)

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
    er.set_defaults(func=_cmd_eval_run)

    rn = subs.add_parser(
        "reenrich",
        help="manually re-queue rows whose taxonomy version is strictly below "
             "v<N>+<hash> (smaller declared N; same-N different-hash is NOT below)",
    )
    rn.add_argument("--taxonomy-below", required=True)
    rn.set_defaults(func=_cmd_reenrich)

    gm = subs.add_parser(
        "golden-merge",
        help="pull JVN admin corrections into golden/seed as label_source='human'",
    )
    gm.add_argument("--since", default=None, help="ISO timestamp lower bound")
    gm.add_argument("--limit", type=int, default=None)
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
