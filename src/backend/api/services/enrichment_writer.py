"""Write one external-enrichment result into the schema.

Called by the internal enrichment router for each item in a POST /results batch,
each wrapped in its own SAVEPOINT by the caller so one bad row never fails the
whole batch. The filterable facets (category/level) land as columns on
job_listings; the heavy/audit payload lands in job_enrichment; tags in job_tags;
and locations reuse JVN's existing Tier-2 writer (persist_llm_result) so cloud
Haiku and the local enricher converge on the same locations/job_locations tables
and the same normalization_status='done' bookkeeping.

No function here commits — the router owns the transaction.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg2.extensions import connection as Connection

from .llm_client import CanonicalLocation
from .location_normalization import normalize_string, persist_llm_result

logger = logging.getLogger(__name__)

# Must match the seeded job_categories / job_levels dimensions + the enricher
# taxonomy SKILL.md. An out-of-enum value is nulled (never 422s the batch) so a
# taxonomy drift on the laptop degrades to "unlabelled", not a dropped batch.
CATEGORY_SLUGS = frozenset(
    {"software_engineering", "product_manager", "data_scientist", "data_engineer", "business"}
)
LEVEL_SLUGS = frozenset({"new_grad", "entry", "mid", "senior", "senior_plus", "manager"})


def _valid(value: Any, allowed: frozenset[str], job_id: str, facet: str) -> str | None:
    if value is None:
        return None
    if value in allowed:
        return str(value)
    logger.warning("enrichment: dropping invalid %s=%r for job %s", facet, value, job_id)
    return None


def apply_result(conn: Connection, result: dict[str, Any], *, require_judge_pass: bool) -> None:
    """Apply one enrichment result. Raises on malformed input so the caller's
    SAVEPOINT rolls back just this row."""
    job_id = result["job_listing_id"]
    judge = result.get("judge") or {}
    needs_human = bool(judge.get("needs_human", False))
    # The judge already applied its corrections on the laptop; publish unless the
    # JVN-side gate is on AND this row is flagged for a human.
    publish = (not require_judge_pass) or (not needs_human)

    category = _valid(result.get("category"), CATEGORY_SLUGS, job_id, "category")
    level = _valid(result.get("level"), LEVEL_SLUGS, job_id, "level")

    cur = conn.cursor()
    try:
        # 1. Audit / heavy payload (1:1 side table).
        cur.execute(
            """
            INSERT INTO job_enrichment (
                job_listing_id, clean_description, classify_confidence,
                classify_reasoning, taxonomy_version, judged, judge_passed,
                judge_confidence, judge_notes, needs_human, enriched_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (job_listing_id) DO UPDATE SET
                clean_description = EXCLUDED.clean_description,
                classify_confidence = EXCLUDED.classify_confidence,
                classify_reasoning = EXCLUDED.classify_reasoning,
                taxonomy_version = EXCLUDED.taxonomy_version,
                judged = EXCLUDED.judged,
                judge_passed = EXCLUDED.judge_passed,
                judge_confidence = EXCLUDED.judge_confidence,
                judge_notes = EXCLUDED.judge_notes,
                needs_human = EXCLUDED.needs_human,
                enriched_at = now()
            """,
            (
                job_id,
                result.get("clean_description"),
                result.get("classify_confidence"),
                result.get("classify_reasoning"),
                result.get("taxonomy_version"),
                bool(judge.get("judged", False)),
                judge.get("passed"),
                judge.get("confidence"),
                judge.get("notes"),
                needs_human,
            ),
        )

        # 2. Facets on job_listings + tags — only when published.
        if publish:
            cur.execute(
                "UPDATE job_listings SET enrichment_category = %s, enrichment_level = %s, "
                "enrichment_status = 'done', enrichment_claimed_at = NULL "
                "WHERE id = %s",
                (category, level, job_id),
            )
            cur.execute("DELETE FROM job_tags WHERE job_listing_id = %s", (job_id,))
            tags = result.get("tags") or []
            seen: set[str] = set()
            for tag in tags:
                t = str(tag).strip().lower()
                if t and t not in seen:
                    seen.add(t)
                    cur.execute(
                        "INSERT INTO job_tags (job_listing_id, tag) VALUES (%s, %s) "
                        "ON CONFLICT (job_listing_id, tag) DO NOTHING",
                        (job_id, t),
                    )
        else:
            cur.execute(
                "UPDATE job_listings SET enrichment_status = 'needs_human', "
                "enrichment_claimed_at = NULL WHERE id = %s",
                (job_id,),
            )
    finally:
        cur.close()

    # 3. Locations — reuse the existing Tier-2 write path (own cursor inside).
    #    This upserts locations/job_locations, refreshes the alias cache, and
    #    sets job_listings.normalization_status='done' exactly like cloud Haiku.
    raw_location = result.get("raw_location")
    loc_dicts = result.get("locations") or []
    if raw_location and loc_dicts:
        locations = [CanonicalLocation(**loc) for loc in loc_dicts]
        persist_llm_result(conn, job_id, normalize_string(raw_location), locations)
