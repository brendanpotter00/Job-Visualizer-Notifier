"""Single source of truth for the observability blob.

Both ``cli health`` / ``cli status`` and the dashboard's ``GET /api/health``
call ``collect_health`` so the two never drift. Pure assembly over a Store — no
network, no I/O beyond the DB (mirrors metrics.py's shape: takes a Store, returns
a dict).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import job_enricher.enrich_config as ec
from job_enricher.store import HEARTBEAT_KEY, Store


def collect_health(store: Store) -> dict[str, Any]:
    """Per-state inbox counts, write-back backlog, heartbeat freshness,
    cumulative per-stage timings, and the latest tick — the laptop's local
    liveness/observability snapshot."""
    with store.connect() as conn:
        inbox = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM inbox GROUP BY status"
            ).fetchall()
        }
        # unsent mirrors what write-back will actually offer: terminal 'failed'
        # (poison) rows are excluded here and surfaced separately via
        # inbox['failed'] + the failed_rows key.
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
    hb_age: float | None = None
    if hb:
        try:
            hb_age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds()
        except ValueError:
            hb_age = None
    return {
        "inbox": inbox,
        "unsent": unsent,
        "needs_human": needs_human,
        "failed_rows": inbox.get("failed", 0),
        # Surfaced so the starvation is VISIBLE while staying unrepaired — both
        # remedies change the live tick's claim order, which r11 declined.
        "starved_null_recency": store.starved_null_recency(),
        "last_heartbeat_at": hb,
        "last_heartbeat_age_s": hb_age,
        "stage_timings": timings,
        "classify_engine": ec.get_classify_engine(store),
        "classify_model": ec.get_classify_model(store),
        "judge_engine": ec.get_judge_engine(store),
        "judge_model": ec.get_judge_model(store),
        "opencode_model": ec.get_opencode_model(store),
        "latest_tick": store.latest_tick(),
    }
