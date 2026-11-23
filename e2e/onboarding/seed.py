"""Seed the onboarding section's database. Idempotent; run before each tier.

Writes, in order:

1. a PURGE of every `e2e|onboarding-*` identity (a previous run's, or an
   aborted one's), so each tier starts with no account but the one below;
2. the PRE-EXISTING account, stamped at a fixed past time with no saved
   filters — the state the migration's backfill leaves every account that
   existed at deploy time (OB-09 / OB-U9);
3. the reveal flag `app_settings.swe_subcategories_enabled = true` — the
   Software Engineering specialties only exist in the questions with it on;
4. the five-row job corpus from `fixtures.py`, tagged with real canonical
   location ids so the Location answer filters the list for real.

RAW SQL, for the reason `subcategories/seed.py` gives: the rows are this
section's INPUT, not its subject. The subject — the `users` stamp and the saved
filters — is only ever written through the product's own endpoints by the
cases themselves. Every statement is scoped to this section's own ids, and the
connection refuses any database but `jobscraper_e2e_onboarding`.

    python -m e2e.onboarding.seed
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from e2e.onboarding import fixtures, identities  # noqa: E402
from e2e.shared.db import assertions as db  # noqa: E402

REVEAL_FLAG_KEY = "swe_subcategories_enabled"

#: Child tables of a job row and the column each is keyed on (see
#: subcategories/seed.py: `job_locations` has no `source_id`).
_CHILD_TABLES = (
    ("job_locations", "job_listing_id"),
    ("job_tags", "source_id"),
    ("job_enrichment", "source_id"),
    ("job_freshness", "source_id"),
)


def _location_ids(cur: Any) -> dict[str, int]:
    """canonical name -> the `locations.id` a city filter resolves to.

    A name can have several rows ("New York, NY, US" is a city AND a region);
    the search resolves to the most-tagged one, lowest id on a tie, and in a
    fresh schema-only clone that is the lowest id. Taking the CITY row keeps
    the tag on the row the city chip means.
    """
    names = sorted({job.location for job in fixtures.JOBS})
    cur.execute(
        "SELECT DISTINCT ON (canonical_name) canonical_name, id FROM locations "
        "WHERE canonical_name = ANY(%s) AND kind = 'city' ORDER BY canonical_name, id",
        (names,),
    )
    found = {r["canonical_name"]: int(r["id"]) for r in cur.fetchall()}
    missing = [n for n in names if n not in found]
    if missing:
        raise AssertionError(
            f"the locations catalog has no city row for {missing}; the clone is missing "
            "the location dimension. Re-provision with `e2e/run.sh onboarding --refresh-db`."
        )
    return found


def _reseed_jobs(cur: Any) -> None:
    cur.execute(
        """
        INSERT INTO companies (id, display_name, ats, board_token, enabled,
                               provider_config, created_at, visibility,
                               consecutive_failures)
        VALUES (%s, %s, 'custom', %s, TRUE, '{}'::jsonb, now(), 'public', 0)
        ON CONFLICT (id) DO UPDATE
           SET display_name = EXCLUDED.display_name, enabled = TRUE, visibility = 'public'
        """,
        (fixtures.COMPANY_ID, fixtures.COMPANY_NAME, fixtures.COMPANY_ID),
    )
    keys = [job.key for job in fixtures.JOBS]
    for table, key in _CHILD_TABLES:
        cur.execute("SELECT to_regclass(%s) AS oid", (table,))
        if cur.fetchone()["oid"] is None:
            continue
        if key == "source_id":
            cur.execute(f"DELETE FROM {table} WHERE source_id = %s", (fixtures.SOURCE_ID,))  # noqa: S608
        else:
            cur.execute(f"DELETE FROM {table} WHERE {key} = ANY(%s)", (keys,))  # noqa: S608
    cur.execute("DELETE FROM job_listings WHERE source_id = %s", (fixtures.SOURCE_ID,))

    loc_ids = _location_ids(cur)
    for index, job in enumerate(fixtures.JOBS):
        cur.execute(
            """
            INSERT INTO job_listings (
                id, title, company, location, url, source_id, details,
                posted_on, created_at, status, has_matched, ai_metadata,
                first_seen_at, details_scraped, normalization_status,
                enrichment_status, enrichment_category, enrichment_level,
                enrichment_subcategories, enrichment_subcategory_source
            ) VALUES (
                %(id)s, %(title)s, %(company)s, %(raw_location)s, %(url)s, %(source_id)s,
                '{}'::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                now() - (%(minutes)s || ' minutes')::interval,
                'OPEN', FALSE, '{}'::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                TRUE, 'done',
                'done', %(category)s, %(level)s,
                %(subcategories)s, %(subcategory_source)s
            )
            """,
            {
                "id": job.key,
                "title": job.title,
                "company": fixtures.COMPANY_ID,
                "raw_location": job.raw_location,
                "url": f"https://example.invalid/{fixtures.SOURCE_ID}/{job.key}",
                "source_id": fixtures.SOURCE_ID,
                "minutes": index,
                "category": job.category,
                "level": job.level,
                "subcategories": job.subcategories,
                "subcategory_source": None if job.subcategories is None else "classify",
            },
        )
        cur.execute(
            "INSERT INTO job_locations (job_listing_id, normalized_location_id, is_primary) "
            "VALUES (%s, %s, TRUE)",
            (job.key, loc_ids[job.location]),
        )


def _seed_preexisting(cur: Any) -> None:
    acct = fixtures.PREEXISTING
    cur.execute(
        """
        INSERT INTO users (id, auth0_id, email, given_name, family_name,
                           created_at, updated_at, onboarding_completed_at)
        VALUES (%s, %s, %s, 'E2E', 'Preexisting', %s, %s, %s::timestamptz)
        """,
        (acct.user_id, acct.sub, acct.email, acct.stamped_at, acct.stamped_at, acct.stamped_at),
    )


def _set_reveal_flag(cur: Any) -> None:
    cur.execute(
        """
        INSERT INTO app_settings (key, value, updated_at, updated_by)
        VALUES (%s, 'true'::jsonb, now(), 'e2e-onboarding')
        ON CONFLICT (key) DO UPDATE
           SET value = 'true'::jsonb, updated_at = now(), updated_by = 'e2e-onboarding'
        """,
        (REVEAL_FLAG_KEY,),
    )


def _assert_schema_has_the_stamp(cur: Any) -> None:
    """The column this whole section is about. A clone without it means the
    source's `alembic_version` claims a revision its schema is not at, so
    `upgrade head` skipped the migration — fail here, naming the fix, rather
    than as a wall of 500s from `GET /api/users`."""
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'users' "
        "AND column_name = 'onboarding_completed_at'"
    )
    if cur.fetchone() is None:
        cur.execute("SELECT version_num FROM alembic_version")
        stamped = [r["version_num"] for r in cur.fetchall()]
        raise AssertionError(
            f"users.onboarding_completed_at is missing although the clone is stamped {stamped}. "
            "The schema source's alembic_version is ahead of its schema. Re-provision with "
            "`E2E_SOURCE_DB_REVISION=<the revision its schema is really at> "
            "e2e/run.sh onboarding --refresh-db` (see e2e/shared/db/ensure_db.sh)."
        )


def reseed(dsn: str = identities.DEFAULT_DSN) -> dict[str, int]:
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            _assert_schema_has_the_stamp(cur)
        purged = identities.purge(conn)
        with conn.cursor() as cur:
            _seed_preexisting(cur)
            _set_reveal_flag(cur)
            _reseed_jobs(cur)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM job_listings WHERE source_id = %s", (fixtures.SOURCE_ID,)
            )
            jobs = int(cur.fetchone()["n"])
            cur.execute("SELECT count(*) AS n FROM job_subcategories")
            subcats = int(cur.fetchone()["n"])
    finally:
        conn.close()
    if jobs != len(fixtures.JOBS):
        raise AssertionError(f"seed wrote {jobs} job rows, expected {len(fixtures.JOBS)}")
    if subcats == 0:
        raise AssertionError(
            "job_subcategories is empty — the specialty accordion would open into "
            "nothing. Re-provision with `e2e/run.sh onboarding --refresh-db`."
        )
    return {"purged": purged, "jobs": jobs, "subcategories": subcats}


if __name__ == "__main__":
    out = reseed()
    print(
        f"seed: purged {out['purged']} old identities; {out['jobs']} job rows; "
        f"{out['subcategories']} specialties; reveal flag ON; pre-existing account stamped "
        f"{fixtures.PREEXISTING.stamped_at}"
    )
