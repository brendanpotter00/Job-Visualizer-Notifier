"""Stage D — durable write-back to JVN.

Batches enriched-but-unsent rows, posts them to JVN /results, and marks them
sent ONLY on a 2xx. Retries with exponential backoff; on persistent failure the
rows stay unsent and the next tick retries (JVN /results is idempotent). Records
stage timing + retry counts for the metrics surface.

Identity is the composite (source_id, job_listing_id) pair — JVN job ids are
NOT globally unique across sources — so JVN's per-row ``failed[]`` entries are
matched back on the pair. Older/partial JVN responses may omit ``source_id`` on
a failed entry: those are matched by bare id only when it is unambiguous within
the batch; ambiguous entries leave every candidate row unsent (retried next
tick) rather than guessing.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import httpx

from job_enricher.jvn_client import JVNClient
from job_enricher.store import Store, now_iso

logger = logging.getLogger(__name__)

# HTTP statuses treated as TRANSIENT (retry with backoff): rate limiting and
# server-side errors — a Railway redeploy 502/503 must not abort the batch.
TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


def _row_to_result(row: Any) -> dict[str, Any]:
    def _loads(v: str | None, default: Any) -> Any:
        if not v:
            return default
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return default

    return {
        "job_listing_id": row["job_listing_id"],
        "source_id": row["source_id"],
        "category": row["category"],
        "level": row["level"],
        "level_includes": _loads(row["level_includes"], []),
        "tags": _loads(row["tags"], []),
        "locations": _loads(row["locations"], []),
        # joined from inbox by enriched_unsent() (heavy fields, only sent here)
        "clean_description": row["clean_description"],
        "raw_location": row["raw_location"],
        # JVN reads these on /results; omitting them left the columns NULL (CR-2).
        "classify_confidence": row["classify_confidence"],
        "classify_reasoning": row["classify_reasoning"],
        "taxonomy_version": row["taxonomy_version"],
        "judge": {
            "judged": bool(row["judged"]),
            "passed": (None if row["judge_pass"] is None else bool(row["judge_pass"])),
            "confidence": row["judge_confidence"],
            "needs_human": bool(row["needs_human"]),
            "notes": row["judge_notes"],
        },
    }


def _log_warnings(warnings: list[Any]) -> None:
    """Log JVN's per-row warnings[] (nulled facets, dropped tags, and the
    'skipped: human-corrected' feedback — the latter means the row counted as
    written but was intentionally not applied over a human correction)."""
    for w in warnings:
        if not isinstance(w, dict):
            continue
        for msg in w.get("warnings") or []:
            logger.warning(
                "JVN warning for (source_id=%s, job_listing_id=%s): %s",
                w.get("source_id"), w.get("job_listing_id"), msg,
            )


def _match_failed_pairs(
    failed_items: list[Any], chunk_pairs: list[tuple[str, str]]
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Resolve JVN failed[] entries to (source_id, job_listing_id) pairs.

    Returns (rejected_pairs, ambiguous_pairs). Entries carrying source_id match
    exactly; entries without it match by bare id ONLY when a single batch row
    carries that id — otherwise every candidate goes into ambiguous_pairs
    (left unsent, no attempts bump: we can't know which row was rejected)."""
    chunk_set = set(chunk_pairs)
    rejected: set[tuple[str, str]] = set()
    ambiguous: set[tuple[str, str]] = set()
    for f in failed_items:
        if not isinstance(f, dict):
            continue
        fid = f.get("job_listing_id")
        fsrc = f.get("source_id")
        if fsrc:
            pair = (fsrc, fid)
            if pair in chunk_set:
                rejected.add(pair)
            else:
                logger.warning(
                    "JVN failed[] names a row not in this batch: source_id=%s "
                    "job_listing_id=%s", fsrc, fid,
                )
            continue
        candidates = [p for p in chunk_pairs if p[1] == fid]
        if len(candidates) == 1:
            rejected.add(candidates[0])
        elif candidates:
            logger.error(
                "JVN failed[] entry for job_listing_id=%s has no source_id and "
                "%d batch rows share that id — leaving all of them unsent",
                fid, len(candidates),
            )
            ambiguous.update(candidates)
        else:
            logger.warning(
                "JVN failed[] names job_listing_id=%s which is not in this batch", fid
            )
    return rejected, ambiguous


def write_back(
    store: Store,
    client: JVNClient | None = None,
    batch_size: int | None = None,
    max_retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Send all unsent enrichments to JVN /results.

    Honors JVN's per-item ``{"written": int, "failed": [...], "warnings":
    [...]}`` response (CR-1): only the (source_id, job_listing_id) pairs JVN
    actually wrote are marked ``sent``; rows JVN rejected in ``failed[]`` stay
    unsent, get their inbox ``attempts`` counter bumped (at
    MAX_WRITEBACK_ATTEMPTS the row becomes terminal 'failed' and stops
    retrying — the poison-row lifecycle), and otherwise retry next tick (the
    endpoint is idempotent). ``warnings[]`` entries are logged. A whole batch
    that never gets a 2xx (transient exhaustion or a non-transient 4xx/auth/
    config error) also stays unsent and counts toward ``errors``; 429/5xx are
    TRANSIENT (retried with backoff), other 4xx fail fast.

    Returns ``{"sent", "batches", "retries", "failed", "unsent", "errors"}``:
      - ``sent``    rows JVN confirmed written this run
      - ``batches`` batches that received a 2xx response
      - ``retries`` transient retries consumed
      - ``failed``  rows JVN rejected per-row (200 with ``failed[]``)
      - ``unsent``  rows still unsent after this run (``failed`` + failed-batch rows)
      - ``errors``  batches that never received a 2xx (operational failures)
    """
    from job_enricher.config import settings

    client = client or JVNClient()
    batch_size = batch_size or settings.writeback_batch_size

    rows = store.enriched_unsent()
    if not rows:
        return {"sent": 0, "batches": 0, "retries": 0, "failed": 0, "unsent": 0, "errors": 0}

    sent = 0
    batches = 0
    retries = 0
    rejected = 0        # per-row JVN rejects (200 with failed[]) + ambiguous holds
    failed_batch_rows = 0  # rows in batches that never got a 2xx
    error_batches = 0
    started = now_iso()
    t0 = time.monotonic()

    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        chunk_pairs = [(r["source_id"], r["job_listing_id"]) for r in chunk]
        payload = [_row_to_result(r) for r in chunk]

        result: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                result = client.post_results(payload)
                break
            except httpx.HTTPStatusError as exc:
                status_code = (
                    exc.response.status_code if exc.response is not None else None
                )
                if status_code in TRANSIENT_HTTP_STATUSES:
                    # 429 / 5xx — classic transient (deploys, restarts, rate
                    # limits): retry with the same capped backoff machinery.
                    last_error = exc
                    retries += 1
                    logger.warning(
                        "write-back batch transient HTTP %s (attempt %d/%d) for %d rows: %s",
                        status_code, attempt + 1, max_retries, len(chunk_pairs), exc,
                    )
                    if attempt < max_retries - 1:
                        sleep(2 ** attempt)
                    continue
                # Other 4xx — non-transient. Do NOT burn the remaining retries
                # silently — surface it now.
                last_error = exc
                logger.error(
                    "write-back batch NON-TRANSIENT HTTP %s for pairs=%s: %s",
                    status_code, chunk_pairs, exc,
                )
                break
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                # Transient network/timeout — retry with exponential backoff.
                last_error = exc
                retries += 1
                logger.warning(
                    "write-back batch transient error (attempt %d/%d) for %d rows: %s",
                    attempt + 1, max_retries, len(chunk_pairs), exc,
                )
                if attempt < max_retries - 1:
                    sleep(2 ** attempt)
            except RuntimeError as exc:
                # The RuntimeError from JVNClient._headers() (missing internal
                # key) — configuration, never transient.
                last_error = exc
                logger.error(
                    "write-back batch NON-TRANSIENT error for pairs=%s: %s",
                    chunk_pairs, exc,
                )
                break

        if result is not None:
            _log_warnings(result.get("warnings") or [])
            failed_items = result.get("failed") or []
            failed_pairs, ambiguous_pairs = _match_failed_pairs(failed_items, chunk_pairs)
            held = failed_pairs | ambiguous_pairs
            success_pairs = [p for p in chunk_pairs if p not in held]
            if success_pairs:
                store.mark_sent(success_pairs)
                sent += len(success_pairs)
            batches += 1
            if held:
                rejected += len(held)
                for f in failed_items:
                    if isinstance(f, dict):
                        logger.error(
                            "JVN rejected (source_id=%s, job_listing_id=%s): %s",
                            f.get("source_id"), f.get("job_listing_id"), f.get("error"),
                        )
                # rejected rows stay unsent -> retry next tick (idempotent),
                # but bump the poison-row attempts counter on the matched rows
                # (ambiguous holds are NOT bumped — we can't know which row
                # JVN actually rejected).
                for pair in failed_pairs:
                    store.record_writeback_failure(*pair)
        else:
            # Whole batch failed (transient exhausted or non-transient); leave
            # every row unsent so the next tick retries.
            error_batches += 1
            failed_batch_rows += len(chunk_pairs)
            logger.error(
                "write-back batch permanently unsent (%d pairs=%s): %s",
                len(chunk_pairs), chunk_pairs, last_error,
            )

    unsent = rejected + failed_batch_rows
    dur_ms = int((time.monotonic() - t0) * 1000)
    store.record_stage_timing(
        "writeback", started, now_iso(), dur_ms, item_count=sent, retry_count=retries
    )
    store.bump_tick_counters(sent=sent, errors=unsent)
    if unsent:
        logger.warning(
            "write-back left %d row(s) unsent (%d JVN-rejected/held, %d in %d failed batch(es)); "
            "they retry next tick",
            unsent, rejected, failed_batch_rows, error_batches,
        )
    return {
        "sent": sent,
        "batches": batches,
        "retries": retries,
        "failed": rejected,
        "unsent": unsent,
        "errors": error_batches,
    }
