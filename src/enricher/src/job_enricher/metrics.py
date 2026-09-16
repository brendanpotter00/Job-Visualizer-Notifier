"""Assemble the per-tick metrics payload pushed to JVN.

POST /api/internal/enrichment/metrics wire contract (snake_case):

  {
    "tick_uuid": str,                     # idempotency key (ticks.uuid)
    "started_at": ISO8601, "ended_at": ISO8601|null,
    "status": "ok"|"error"|"running", "notes": str|null,
    "counters": {...},                    # EVERY store.TICK_COUNTER_COLS column:
                                          # claimed, cleaned, classified, judged,
                                          # corrected, needs_human, sent, errors,
                                          # nulled_facets, swe_classified,
                                          # swe_subcat_evaluated, swe_subcategorized
    "duration_s": float,
    "taxonomy_version": str|null,
    "knobs": {...},                       # enrich_config snapshot (small)
    "stage_timings": [{stage, ms, items, retries}],
    "heartbeat_age_s": float|null,
    "scorecard": dict|null,               # only when its hash is NEW
    "enricher_version": str|null,
    "drift_suspected": bool
  }

The scorecard is included only when its content hash differs from the meta key
``metrics:last_scorecard_hash``; the caller updates that key AFTER a successful
POST so a failed push re-sends it next time. Pure assembly — no network here.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from job_enricher import __version__
from job_enricher.store import (
    HEARTBEAT_KEY,
    LAST_SCORECARD_HASH_KEY,
    TICK_COUNTER_COLS,
    Store,
)

logger = logging.getLogger(__name__)

# mass-nulling circuit breaker (drift detector): with at least this many
# classified rows, a nulled-facet share above the ratio means the taxonomy has
# probably drifted from what the agents emit — the tick should not close ok.
DRIFT_MIN_CLASSIFIED = 10
DRIFT_NULLED_RATIO = 0.5


def drift_suspected(counters: dict[str, Any]) -> bool:
    classified = int(counters.get("classified") or 0)
    nulled = int(counters.get("nulled_facets") or 0)
    return classified >= DRIFT_MIN_CLASSIFIED and nulled > DRIFT_NULLED_RATIO * classified


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _heartbeat_age_s(store: Store) -> float | None:
    hb = _parse_iso(store.get_meta(HEARTBEAT_KEY))
    if hb is None:
        return None
    return (datetime.now(timezone.utc) - hb).total_seconds()


def _duration_s(started_at: str | None, ended_at: str | None) -> float:
    start = _parse_iso(started_at)
    if start is None:
        return 0.0
    end = _parse_iso(ended_at) or datetime.now(timezone.utc)
    return max((end - start).total_seconds(), 0.0)


def _fresh_scorecard(store: Store) -> tuple[dict[str, Any] | None, str | None]:
    """(scorecard_json, content_hash) when golden/scorecards/scorecard.json
    exists AND its hash differs from the last one pushed; (None, None) otherwise."""
    from job_enricher.eval.golden import SCORECARD_DIR

    path = SCORECARD_DIR / "scorecard.json"
    if not path.exists():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
        card = json.loads(raw)
    except (OSError, ValueError) as exc:
        logger.warning("metrics: unreadable scorecard at %s: %s", path, exc)
        return None, None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if digest == store.get_meta(LAST_SCORECARD_HASH_KEY):
        return None, None
    return card, digest


def build_metrics_payload(
    store: Store, tick_id: int | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """Assemble the /metrics payload for `tick_id` (default: the latest tick).

    Returns (payload, scorecard_hash) — scorecard_hash is non-None only when a
    NEW scorecard rode along; the caller stores it under
    ``metrics:last_scorecard_hash`` after a successful POST. Returns
    (None, None) when there is no tick to report."""
    from job_enricher import enrich_config as ec

    tick = store.get_tick(tick_id) if tick_id is not None else store.latest_tick()
    if tick is None:
        return None, None
    tick_uuid = store.ensure_tick_uuid(int(tick["id"]))

    # ⚠ DERIVED FROM `store.TICK_COUNTER_COLS`, NEVER RE-TYPED HERE. This used to
    # be a second hand-written tuple, and the two lists drifted the moment v4
    # added `swe_classified` / `swe_subcat_evaluated` / `swe_subcategorized`:
    # bump_tick_counters wrote them to the ticks table correctly, this function
    # dropped them, and JVN's `subcategory_empty_drift` breaker read NOTHING —
    # silently, since a missing key is not an error on either side. The column
    # set IS the wire contract; there is no second place to keep in step.
    counters = {c: int(tick.get(c) or 0) for c in sorted(TICK_COUNTER_COLS)}

    try:
        from job_enricher import taxonomy as tax

        taxonomy_version: str | None = tax.taxonomy_version()
    except OSError:
        taxonomy_version = None

    stage_timings = [
        {
            "stage": t["stage"],
            "ms": float(t["duration_ms"]),
            "items": int(t["item_count"]),
            "retries": int(t["retry_count"]),
        }
        for t in store.stage_timings_for_tick(int(tick["id"]))
    ]

    scorecard, scorecard_hash = _fresh_scorecard(store)

    payload: dict[str, Any] = {
        "tick_uuid": tick_uuid,
        "started_at": tick["started_at"],
        "ended_at": tick["ended_at"],
        "status": tick["status"],
        "notes": tick["notes"],
        "counters": counters,
        "duration_s": round(_duration_s(tick["started_at"], tick["ended_at"]), 3),
        "taxonomy_version": taxonomy_version,
        "knobs": ec.config_snapshot(store),
        "stage_timings": stage_timings,
        "engine_latency_ms": store.latency_summary_for_tick(int(tick["id"])),
        "heartbeat_age_s": _heartbeat_age_s(store),
        "scorecard": scorecard,
        "enricher_version": __version__,
        "drift_suspected": drift_suspected(counters),
    }
    return payload, scorecard_hash
