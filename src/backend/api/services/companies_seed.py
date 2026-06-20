"""Idempotent seed of curated company directory content (blurb + accomplishment).

Called from FastAPI lifespan on every boot, mirroring ``features_seed``. The
committed ``data/company_profiles.json`` is the source of truth: blurb /
accomplishment are re-applied on each boot so editing the JSON ships on the next
deploy.

Two phases, one transaction:
1. **Ensure script-scraped rows exist.** Google / Apple / Microsoft are scraped
   by Python scripts (the auto-scraper drives them *by name*), not by the
   Procrastinate worker, so they have no row in ``companies``. We register them
   with the sentinel ats ``"script"`` so the directory page can list them.
   ``"script"`` is matched by NONE of the per-ATS fan-out queries (those filter
   ``WHERE ats = 'greenhouse'|'ashby'|'lever'|'gem'|'eightfold'|'workday'``), so
   these rows are **never enqueued or scraped** — verified by
   ``test_companies_seed``. ``INSERT ... ON CONFLICT (id) DO NOTHING`` keeps it
   idempotent and never clobbers an operator-managed row.
2. **Upsert blurb + accomplishment** for every profile id. ``UPDATE`` no-ops on
   ids absent from ``companies`` (a profile for a company not yet seeded), which
   we count and WARNING-log so the mismatch is debuggable without failing boot.
"""

import json
import logging
from pathlib import Path
from typing import cast

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

# Sentinel ats for custom/script-scraped companies (Google/Apple/Microsoft).
# Deliberately NOT one of the worker ATS values, so fan-out never selects them.
SCRIPT_ATS = "script"

# Script-scraped companies have been available on the site since long before
# they had a ``companies`` row (they were scraped by name, listed via the
# frontend config). Insert them with a backdated ``created_at`` so the
# auto-enroll watermark in ``user_preferences_service`` treats them as the
# pre-existing companies they are — NOT as newly launched ones. Without this,
# every auto-enroll user would have google/apple/microsoft force-added to their
# feed on the deploy that ships this row (created_at > their watermark).
_BACKFILL_CREATED_AT = "2020-01-01T00:00:00+00:00"

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "company_profiles.json"

_COMPANIES_TABLE = sql.Identifier("companies")


def _load_profiles() -> dict:
    """Load the committed company-profiles JSON.

    Shape: ``{ "<id>": { "blurb": str, "accomplishment": str,
    ["displayName": str, "ats": str, "boardToken": str] } }``. The optional
    row-creation fields are present only on script-scraped companies.
    """
    with open(_DATA_PATH, encoding="utf-8") as fh:
        # json.load is untyped (-> Any); the committed file is a JSON object.
        return cast(dict, json.load(fh))


def seed_company_profiles(
    conn: Connection, profiles: dict | None = None
) -> dict:
    """Ensure script rows exist and upsert blurb/accomplishment. Idempotent.

    Commits on success. Rolls back + re-raises on database error. Returns a
    summary dict ``{script_inserted, updated, unmatched}``. ``profiles`` may be
    overridden for tests; otherwise the committed JSON is loaded lazily.
    """
    if profiles is None:
        # Loaded lazily (NOT at module import) so a malformed/unreadable
        # company_profiles.json degrades the directory's content rather than
        # breaking module import for every consumer and test. The lifespan call
        # site wraps this in a broad except, so a content problem soft-fails
        # (serves last-good DB content) instead of crash-looping boot.
        profiles = _load_profiles()

    cursor = conn.cursor()
    script_inserted = 0
    updated = 0
    unmatched: list[str] = []
    try:
        # Phase 1: register script-scraped companies (idempotent).
        for company_id, profile in profiles.items():
            ats = profile.get("ats")
            if not ats:
                continue
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {} (id, display_name, ats, board_token, enabled, created_at)"
                    " VALUES (%s, %s, %s, %s, TRUE, %s)"
                    " ON CONFLICT (id) DO NOTHING"
                ).format(_COMPANIES_TABLE),
                (
                    company_id,
                    profile.get("displayName", company_id),
                    ats,
                    profile.get("boardToken", company_id),
                    _BACKFILL_CREATED_AT,
                ),
            )
            if cursor.rowcount == 1:
                script_inserted += 1

        # Phase 2: upsert directory content (file is source of truth).
        for company_id, profile in profiles.items():
            cursor.execute(
                sql.SQL(
                    "UPDATE {} SET blurb = %s, accomplishment = %s WHERE id = %s"
                ).format(_COMPANIES_TABLE),
                (profile.get("blurb"), profile.get("accomplishment"), company_id),
            )
            if cursor.rowcount == 1:
                updated += 1
            else:
                unmatched.append(company_id)

        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error during seed_company_profiles: %s", exc, exc_info=True,
        )
        raise

    if unmatched:
        logger.warning(
            "seed_company_profiles: %d profile id(s) matched no companies row: %s",
            len(unmatched),
            ", ".join(sorted(unmatched)),
        )
    # Emit unconditionally so cold-start logs always show the seed ran (matches
    # features_seed rationale — a conditional log is indistinguishable from a
    # silent crash in Railway logs).
    logger.info(
        "seed_company_profiles completed (script_inserted=%d, updated=%d, unmatched=%d)",
        script_inserted, updated, len(unmatched),
    )
    return {
        "script_inserted": script_inserted,
        "updated": updated,
        "unmatched": unmatched,
    }
