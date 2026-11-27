"""Write the :mod:`fixtures` corpus into the section's database.

Reached three ways, all through :func:`reseed`: `run.sh` once after the stack
is up, `api/conftest.py` before every test, and by hand
(`python e2e/company-categories/seed.py`) for a fix loop on a `--keep-up` stack.

RAW SQL, for the reason `subcategories/seed.py` gives: the rows are this
section's INPUT. Its SUBJECT (the membership tables, facets, the search
filter, saved filters) is only ever written by the product itself: the backend
seeds `company_categories` / `company_category_members` from the committed
JSON on boot, and the cases save filters through the real endpoints.

Every statement is scoped to this section's `source_id`, its fixture ids or its
one reader identity, and the connection refuses any database but
`jobscraper_e2e_company_categories`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
for _p in (str(_REPO_ROOT), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures  # noqa: E402

from e2e.shared.db import assertions as db  # noqa: E402

DEFAULT_DSN = os.environ.get(
    "E2E_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e_company_categories",
)

READER_SUB = fixtures.READER_SUB
READER_EMAIL = fixtures.READER_EMAIL
READER_USER_ID = "e2ecompanycategoriesreader"

_CHILD_TABLES = (
    ("job_locations", "job_listing_id"),
    ("job_tags", "source_id"),
    ("job_enrichment", "source_id"),
    ("job_freshness", "source_id"),
)


def _ensure_companies(cur: Any) -> None:
    for company_id, name in fixtures.COMPANY_NAMES.items():
        if company_id == fixtures.DECOY_COMPANY_ID:
            cur.execute(
                """
                INSERT INTO companies (id, display_name, ats, board_token, enabled,
                                       provider_config, created_at, visibility,
                                       consecutive_failures)
                VALUES (%s, %s, 'custom', %s, TRUE, '{}'::jsonb, now(), 'public', 0)
                ON CONFLICT (id) DO UPDATE
                   SET display_name = EXCLUDED.display_name, enabled = TRUE,
                       visibility = 'public'
                """,
                (company_id, name, company_id),
            )
        else:
            # A REAL company: the boot seed may already own its row (Google is
            # a `script` company). DO NOTHING, never rewrite it; `script` is
            # matched by no worker fan-out, so nothing is ever scraped.
            cur.execute(
                """
                INSERT INTO companies (id, display_name, ats, board_token, enabled, created_at)
                VALUES (%s, %s, 'script', %s, TRUE, now())
                ON CONFLICT (id) DO NOTHING
                """,
                (company_id, name, company_id),
            )


def _delete_fixture_jobs(cur: Any) -> None:
    ids = [job.key for job in fixtures.JOBS]
    for table, key in _CHILD_TABLES:
        cur.execute("SELECT to_regclass(%s) AS oid", (table,))
        if cur.fetchone()["oid"] is None:
            continue
        if key == "source_id":
            cur.execute(f"DELETE FROM {table} WHERE source_id = %s", (fixtures.SOURCE_ID,))  # noqa: S608
        else:
            cur.execute(f"DELETE FROM {table} WHERE {key} = ANY(%s)", (ids,))  # noqa: S608
    cur.execute("DELETE FROM job_listings WHERE source_id = %s", (fixtures.SOURCE_ID,))


def _insert_jobs(cur: Any) -> None:
    for index, job in enumerate(fixtures.JOBS):
        # first_seen_at one minute apart, newest first in fixture order, so the
        # keyset order is deterministic and a cursor walk means something.
        cur.execute(
            """
            INSERT INTO job_listings (
                id, title, company, location, url, source_id, details,
                posted_on, created_at, status, has_matched, ai_metadata,
                first_seen_at, details_scraped, normalization_status,
                enrichment_status, enrichment_category, enrichment_level
            ) VALUES (
                %(id)s, %(title)s, %(company)s, 'Remote', %(url)s, %(source_id)s,
                '{}'::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                now() - (%(minutes)s || ' minutes')::interval,
                'OPEN', FALSE, '{}'::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                TRUE, 'done',
                'done', %(category)s, %(level)s
            )
            """,
            {
                "id": job.key,
                "title": job.title,
                "company": job.company,
                "url": f"https://example.invalid/{fixtures.SOURCE_ID}/{job.key}",
                "source_id": fixtures.SOURCE_ID,
                "minutes": index,
                "category": job.category,
                "level": job.level,
            },
        )


def _ensure_reader_onboarded(cur: Any) -> None:
    """The reader is an existing, already-onboarded account. A brand-new one
    would get the first-sign-in questions over every page (that flow is the
    `onboarding` section's subject, not this one's)."""
    cur.execute(
        """
        INSERT INTO users (id, auth0_id, email, given_name, family_name,
                           created_at, updated_at, onboarding_completed_at)
        SELECT %s, %s, %s, 'E2E', 'Reader', now(), now(), now()
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE auth0_id = %s OR email = %s)
        """,
        (READER_USER_ID, READER_SUB, READER_EMAIL, READER_SUB, READER_EMAIL),
    )
    cur.execute(
        "UPDATE users SET onboarding_completed_at = COALESCE(onboarding_completed_at, now()) "
        "WHERE auth0_id = %s OR email = %s",
        (READER_SUB, READER_EMAIL),
    )


def _clear_reader_saved_filters(cur: Any) -> None:
    cur.execute(
        "DELETE FROM user_saved_filters WHERE user_id IN "
        "(SELECT id FROM users WHERE auth0_id = %s OR email = %s)",
        (READER_SUB, READER_EMAIL),
    )


def assert_membership_seeded(dsn: str = DEFAULT_DSN) -> int:
    """The boot seed wrote every category in the JSON, with every member.

    Checked before any case: a backend that failed its seed (it soft-fails so
    boot never crash-loops) would make every case below fail in a way that
    reads like a broken filter.
    """
    cats = fixtures.load_categories()
    expected_members = sum(len(c["companyIds"]) for c in cats)
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('company_category_members') AS oid")
            if cur.fetchone()["oid"] is None:
                raise AssertionError(
                    "company_category_members does not exist: the clone is behind the "
                    "company categories migration, which the backend applies on boot."
                )
            cur.execute("SELECT count(*) AS n FROM company_category_members")
            members = int(cur.fetchone()["n"])
    finally:
        conn.close()
    if members != expected_members:
        raise AssertionError(
            f"company_category_members holds {members} rows, the JSON has {expected_members}. "
            "The boot seed did not run (see backend.log for 'company categories')."
        )
    return members


def reseed(dsn: str = DEFAULT_DSN) -> int:
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            _ensure_companies(cur)
            _delete_fixture_jobs(cur)
            _insert_jobs(cur)
            _ensure_reader_onboarded(cur)
            _clear_reader_saved_filters(cur)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM job_listings WHERE source_id = %s", (fixtures.SOURCE_ID,)
            )
            written = int(cur.fetchone()["n"])
    finally:
        conn.close()
    if written != len(fixtures.JOBS):
        raise AssertionError(f"seed wrote {written} rows, expected {len(fixtures.JOBS)}")
    return written


if __name__ == "__main__":
    members = assert_membership_seeded()
    n = reseed()
    print(f"seed: {n} job rows; {members} company-category memberships seeded by the backend")
