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


# ---- BF-11: the two subcategory drift breakers -----------------------------
# ⚠ `drift_suspected` above fires ONLY on `nulled_facets`. A classify wave that
# emitted `[]` for every SWE row produces ZERO nulled facets, so the tick closes
# `status=ok` and JVN's verdict banner stays green. This worker has a documented
# history of ticks reporting `status=ok` while dead — a green banner is not
# evidence. These two detectors are the ones that see it.
#
# ⚠ COUNTER SEMANTICS, stated once and used everywhere:
#   `swe_subcat_evaluated` counts rows whose recorded subcategories value is
#       NON-NULL, INCLUDING `[]`. This is COVERAGE, and it is the definition
#       JVN's coverage tile already uses.
#   `swe_subcategorized` counts rows whose recorded list is NON-EMPTY. This is
#       YIELD.
# They are DIFFERENT detectors and conflating them is what made the draft's
# single breaker blind.

# UNMEASURED — placeholder; set by BF-11
#   Justified by the measured 4-27 SWE rows per tick (median ~17) over the last
#   20 ticks on the live DB. ⚠ RE-MEASURE BEFORE SHIPPING: if the median moves
#   the window moves with it, because the whole point is that the breaker is
#   armed on essentially every tick-end rather than a quarter of them.
SUBCAT_DRIFT_MIN_SWE = 10

# UNMEASURED — placeholder; set by BF-11
#   ⚠ A ROLLING WINDOW, NOT A SINGLE TICK. At 4-27 SWE rows per tick a
#   single-tick N=10 threshold is SILENT on roughly a quarter of ticks. Three
#   ticks at the median is ~51 SWE rows, so the breaker is armed at essentially
#   every tick-end. Same measurement as SUBCAT_DRIFT_MIN_SWE; re-measure with it.
SUBCAT_DRIFT_WINDOW_TICKS = 3

_SUBCAT_COUNTERS = ("swe_classified", "swe_subcat_evaluated", "swe_subcategorized")


def window_counters(store: Store, n: int = SUBCAT_DRIFT_WINDOW_TICKS) -> dict[str, int]:
    """Sum the three subcategory counters over the last `n` ticks, INCLUDING the
    one being closed (its row already exists, with status 'running')."""
    totals = dict.fromkeys(_SUBCAT_COUNTERS, 0)
    for tick in store.recent_ticks(limit=max(1, n)):
        for col in _SUBCAT_COUNTERS:
            totals[col] += int(tick.get(col) or 0)
    return totals


def subcategory_absent_drift(window: dict[str, Any]) -> bool:
    """THE FIELD NEVER ARRIVED AT ALL — a broken prompt, schema or engine.

    ⚠ An ABSOLUTE-ZERO test, deliberately not a ratio: "N SWE rows classified and
    not one carried an evaluated subcategory field" is unambiguous, where a ratio
    would either miss real drift or flap."""
    classified = int(window.get("swe_classified") or 0)
    evaluated = int(window.get("swe_subcat_evaluated") or 0)
    return classified >= SUBCAT_DRIFT_MIN_SWE and evaluated == 0


def subcategory_empty_drift(window: dict[str, Any]) -> bool:
    """THE FIELD ARRIVED AND EVERY ANSWER WAS `[]` — a broken rubric.

    ⚠ This is the detector that MATTERS, and the one the draft was missing,
    because `'[]'` is TERMINAL: those rows leave the backfill queue permanently
    and only BF-14 can bring them back. Also an absolute-zero test — a legitimate
    `[]` rate is high and layer-dependent, so a ratio would flap."""
    evaluated = int(window.get("swe_subcat_evaluated") or 0)
    labelled = int(window.get("swe_subcategorized") or 0)
    return evaluated >= SUBCAT_DRIFT_MIN_SWE and labelled == 0


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
    window = window_counters(store)

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
        # BF-11: the rolling-window subcategory breakers, beside the per-tick one.
        "subcategory_absent_drift": subcategory_absent_drift(window),
        "subcategory_empty_drift": subcategory_empty_drift(window),
        "subcategory_window": window,
    }
    return payload, scorecard_hash
