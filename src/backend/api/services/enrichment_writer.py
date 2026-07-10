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
    {
        "software_engineering",
        "hardware_engineer",
        "product_manager",
        "project_manager",
        "data_scientist",
        "growth",
        "business_ops",
    }
)
LEVEL_SLUGS = frozenset({"new_grad", "entry", "mid", "senior", "senior_plus", "manager"})

# Bounds on what one /results item may persist into the public read path
# (job_tags feeds every /api/jobs row via the tags subquery). Extras are
# truncated with a warning — degraded, never a dropped batch, mirroring the
# facet soft-nulling contract.
MAX_TAGS_PER_JOB = 16
MAX_TAG_LENGTH = 60


def _valid(
    value: Any, allowed: frozenset[str], job_id: str, facet: str, warnings: list[str]
) -> str | None:
    if value is None:
        return None
    if value in allowed:
        return str(value)
    logger.warning("enrichment: dropping invalid %s=%r for job %s", facet, value, job_id)
    # Also surfaced in the /results response so the enricher SEES the
    # degradation — silently-nulled facets are how taxonomy drift stays
    # invisible for weeks.
    warnings.append(f"invalid {facet} {value!r} nulled (not in taxonomy)")
    return None


def apply_result(
    conn: Connection, result: dict[str, Any], *, require_judge_pass: bool
) -> list[str]:
    """Apply one enrichment result. Raises on malformed input so the caller's
    SAVEPOINT rolls back just this row.

    Returns the row's degradation warnings (facet nulled, tags truncated,
    human-correction skip); the router echoes them in the /results response —
    the write-side feedback channel that makes laptop-side drift observable
    instead of silent."""
    warnings: list[str] = []
    job_id = result["job_listing_id"]
    # job_listings' PK is the COMPOSITE (source_id, id); `id` is NOT globally
    # unique, so every job_listings UPDATE below keys on BOTH columns. The
    # enricher sends source_id in each /results item — a missing one is a
    # per-row failure (rolled back by the caller's SAVEPOINT), never a guess.
    source_id = result.get("source_id")
    if not source_id:
        raise ValueError(f"missing source_id for job_listing_id={job_id!r}")
    judge = result.get("judge") or {}
    needs_human = bool(judge.get("needs_human", False))
    # The judge already applied its corrections on the laptop; publish unless the
    # JVN-side gate is on AND this row is flagged for a human.
    publish = (not require_judge_pass) or (not needs_human)

    category = _valid(result.get("category"), CATEGORY_SLUGS, job_id, "category", warnings)
    level = _valid(result.get("level"), LEVEL_SLUGS, job_id, "level", warnings)

    cur = conn.cursor()
    try:
        # 0. Human-correction guard: a row an admin has corrected is LOCKED
        #    against automated overwrite — a human label must outlive any later
        #    agent re-write (reenrich sweeps, duplicate deliveries, taxonomy
        #    re-runs). The item still counts as written (the enricher marks it
        #    sent and stops retrying); the warning tells it why nothing changed.
        #    Only the admin re-enrich action (which clears human_corrected_at)
        #    reopens the row.
        cur.execute(
            "SELECT human_corrected_at FROM job_enrichment "
            "WHERE source_id = %s AND job_listing_id = %s",
            (source_id, job_id),
        )
        guard_row = cur.fetchone()
        if guard_row and guard_row["human_corrected_at"] is not None:
            logger.info(
                "enrichment: skipping (source_id=%s, id=%s) — human-corrected at %s",
                source_id, job_id, guard_row["human_corrected_at"],
            )
            warnings.append("skipped: human-corrected (facets locked)")
            return warnings
        # 1. Audit / heavy payload (1:1 side table). Keyed on the composite
        #    (source_id, job_listing_id) — `id` is not globally unique, so an
        #    upsert on job_listing_id alone could collapse a different source's row.
        cur.execute(
            """
            INSERT INTO job_enrichment (
                source_id, job_listing_id, clean_description, classify_confidence,
                classify_reasoning, taxonomy_version, judged, judge_passed,
                judge_confidence, judge_notes, needs_human, enriched_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (source_id, job_listing_id) DO UPDATE SET
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
                source_id,
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

        # 2. Facets on job_listings + tags — only when published. Keyed on the
        #    composite PK (source_id, id).
        if publish:
            cur.execute(
                "UPDATE job_listings SET enrichment_category = %s, enrichment_level = %s, "
                "enrichment_status = 'done', enrichment_claimed_at = NULL "
                "WHERE source_id = %s AND id = %s",
                (category, level, source_id, job_id),
            )
            # A well-formed but nonexistent/stale (source_id, id) matches 0 rows.
            # Raise so the caller's SAVEPOINT rolls back the already-inserted
            # job_enrichment audit row (+ tags) — no orphan side-table rows, no
            # false `written`; the item routes to per-row failed[] instead.
            if cur.rowcount == 0:
                raise ValueError(
                    f"no job_listings row for (source_id={source_id!r}, "
                    f"id={job_id!r}) — nothing updated"
                )
            cur.execute(
                "DELETE FROM job_tags WHERE source_id = %s AND job_listing_id = %s",
                (source_id, job_id),
            )
            tags = result.get("tags") or []
            seen: set[str] = set()
            for tag in tags:
                t = str(tag).strip().lower()
                if not t or t in seen:
                    continue
                if len(t) > MAX_TAG_LENGTH:
                    warnings.append(f"tag dropped (> {MAX_TAG_LENGTH} chars): {t[:40]!r}…")
                    continue
                if len(seen) >= MAX_TAGS_PER_JOB:
                    warnings.append(
                        f"tags truncated to {MAX_TAGS_PER_JOB} (got {len(tags)})"
                    )
                    break
                seen.add(t)
                cur.execute(
                    "INSERT INTO job_tags (source_id, job_listing_id, tag) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (source_id, job_listing_id, tag) DO NOTHING",
                    (source_id, job_id, t),
                )
        else:
            # Demote to needs_human: also NULL the facets + drop the tags so a row
            # previously published 'done' doesn't retain stale published facets
            # after being re-flagged for a human.
            cur.execute(
                "UPDATE job_listings SET enrichment_category = NULL, enrichment_level = NULL, "
                "enrichment_status = 'needs_human', enrichment_claimed_at = NULL "
                "WHERE source_id = %s AND id = %s",
                (source_id, job_id),
            )
            # Same 0-row guard as the publish branch: a nonexistent/stale
            # (source_id, id) must fail the row (rolling back the audit insert),
            # not silently demote nothing while counting as `written`.
            if cur.rowcount == 0:
                raise ValueError(
                    f"no job_listings row for (source_id={source_id!r}, "
                    f"id={job_id!r}) — nothing updated"
                )
            cur.execute(
                "DELETE FROM job_tags WHERE source_id = %s AND job_listing_id = %s",
                (source_id, job_id),
            )
    finally:
        cur.close()

    # 3. Locations — reuse the existing Tier-2 write path in its OWN nested
    #    savepoint, AFTER labels+status are committed to this row. A malformed or
    #    failing locations[] element (CanonicalLocation validators, persist
    #    errors) must degrade to "labels persisted, row still done, location
    #    skipped + warning" — it must NEVER roll back the good facets/tags above.
    raw_location = result.get("raw_location")
    loc_dicts = result.get("locations") or []
    if raw_location and loc_dicts:
        loc_cur = conn.cursor()
        try:
            loc_cur.execute("SAVEPOINT enr_loc")
            # `loc_dicts` is truthy here (non-empty), so persist_llm_result's
            # avg-confidence divide never hits an empty sequence (ZeroDivision).
            locations = [CanonicalLocation(**loc) for loc in loc_dicts]
            persist_llm_result(conn, job_id, normalize_string(raw_location), locations)
            loc_cur.execute("RELEASE SAVEPOINT enr_loc")
        except Exception as exc:  # noqa: BLE001 — a bad location must not nuke labels
            loc_cur.execute("ROLLBACK TO SAVEPOINT enr_loc")
            # exc_info=True captures the traceback: a CanonicalLocation validation
            # error is expected/benign, but a psycopg2 or programming error hiding
            # in this subset must be debuggable, not just str()'d away.
            logger.warning(
                "enrichment: skipping locations for job %s (labels kept, row still "
                "done): %s",
                job_id, exc, exc_info=True,
            )
            warnings.append("locations skipped (persist failed; labels kept)")
        finally:
            loc_cur.close()
    elif bool(raw_location) != bool(loc_dicts):
        # Exactly one of raw_location / locations[] is present — can't persist a
        # location without both. Skip + warn (row still done with its labels)
        # rather than silently dropping the half we got.
        logger.warning(
            "enrichment: partial location for job %s (raw_location=%s, locations=%s); "
            "skipping location persist",
            job_id, bool(raw_location), bool(loc_dicts),
        )
        warnings.append("partial location (raw_location XOR locations[]) skipped")
    return warnings
