"""Write the :mod:`fixtures` corpus into the section's database.

Reached three ways, and all three go through :func:`reseed`:

* ``run.sh`` calls it once after the stack is up, so the UI tier has rows.
* ``api/conftest.py`` calls it per-test (autouse), so one case cannot leave
  state that changes another's answer — the same "re-runnable back to back with
  no manual reset" rule `add-companies` applies at test granularity.
* ``python -m e2e.subcategories.seed`` by hand, for a fix loop against a stack
  left up with ``--keep-up``.

WHY RAW SQL AND NOT THE PRODUCT'S OWN WRITE PATH. `add-companies`' §8 rule is
that a test must mutate through the product's endpoints, never a hand-written
DELETE — and it is right, because the thing IT tests is those endpoints. The
write path here is the ENRICHER, which reaches this column over
``POST /api/internal/enrichment/results`` behind an internal key, and driving it
would make every case in this section depend on the enricher's contract in order
to assert something about the READER's SQL. The column, not the writer, is this
section's subject. So: raw SQL, fenced by :func:`assertions.connect`'s database
guard, and confined to rows carrying this section's own ``source_id``.

NOTHING HERE TOUCHES A ROW IT DID NOT WRITE. Every statement is keyed on
``source_id = 'e2e_subcategories'`` or on the two fixture company ids. A
schema-only database has no other rows to hit, but the scoping is what makes
that a property of the code rather than of the day's data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

import fixtures  # noqa: E402

from e2e.shared.db import assertions as db  # noqa: E402

#: Default DSN for the section's own database. `run.sh` exports the same value
#: as `E2E_DATABASE_URL`; the fallback keeps a hand-run `python -m ...` working.
DEFAULT_DSN = os.environ.get(
    "E2E_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e_subcategories",
)

REVEAL_FLAG_KEY = "swe_subcategories_enabled"


def _upsert_companies(cur: Any) -> None:
    for company in fixtures.ALL_COMPANIES:
        cur.execute(
            """
            INSERT INTO companies (id, display_name, ats, board_token, enabled,
                                   provider_config, created_at, visibility,
                                   consecutive_failures)
            VALUES (%s, %s, 'custom', %s, TRUE, '{}'::jsonb, now(), 'public', 0)
            ON CONFLICT (id) DO UPDATE
               SET display_name = EXCLUDED.display_name,
                   enabled = TRUE,
                   visibility = 'public'
            """,
            (company.id, company.display_name, company.id),
        )


#: Child tables, and the column each one is actually keyed on. NOT a single
#: `source_id` loop: `job_locations` is keyed on `job_listing_id` ALONE — it
#: carries no `source_id` at all — so a uniform delete raises `UndefinedColumn`
#: and takes the whole seed with it. Listed explicitly rather than introspected
#: because "which column identifies my rows" is a fact about the schema that
#: should be read, not guessed, when the answer decides what gets deleted.
_CHILD_TABLES = (
    ("job_locations", "job_listing_id"),
    ("job_tags", "source_id"),
    ("job_enrichment", "source_id"),
    # Populated by the `job_freshness_sync_after_insert` trigger, so nothing
    # inserts into it by hand — but it holds a composite FK onto job_listings
    # and therefore has to go by hand on the way OUT.
    ("job_freshness", "source_id"),
)


def _delete_fixture_jobs(cur: Any) -> None:
    fixture_ids = [job.job_id for job in fixtures.JOBS]
    for table, key in _CHILD_TABLES:
        cur.execute("SELECT to_regclass(%s) AS oid", (table,))
        if cur.fetchone()["oid"] is None:
            continue
        if key == "source_id":
            cur.execute(f"DELETE FROM {table} WHERE source_id = %s", (fixtures.SOURCE_ID,))
        else:
            # Scoped to THIS section's fixture ids, which are unique to it
            # ("J-BACKEND" and friends). A table with no source_id cannot be
            # scoped by namespace, so it is scoped by the id list instead —
            # never by a bare DELETE.
            cur.execute(f"DELETE FROM {table} WHERE {key} = ANY(%s)", (fixture_ids,))
    cur.execute("DELETE FROM job_listings WHERE source_id = %s", (fixtures.SOURCE_ID,))


def _insert_jobs(cur: Any) -> None:
    for index, job in enumerate(fixtures.JOBS):
        # `first_seen_at` DESCENDING by fixture order, one minute apart. The
        # keyset order is (first_seen_at DESC, source_id DESC, id DESC), so
        # distinct values make the page order deterministic and make a
        # cursor walk meaningful; identical values would leave the tiebreak
        # to do all the work and hide an ordering regression.
        cur.execute(
            """
            INSERT INTO job_listings (
                id, title, company, location, url, source_id, details,
                posted_on, created_at, status, has_matched, ai_metadata,
                first_seen_at, details_scraped, normalization_status,
                enrichment_status, enrichment_category, enrichment_level,
                enrichment_subcategories, enrichment_subcategory_source
            ) VALUES (
                %(id)s, %(title)s, %(company)s, 'Remote', %(url)s, %(source_id)s,
                '{}'::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                now() - (%(minutes)s || ' minutes')::interval,
                'OPEN', FALSE, '{}'::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                TRUE, 'done',
                'done', %(category)s, %(level)s,
                %(subcategories)s, %(source)s
            )
            """,
            {
                "id": job.job_id,
                "title": job.title,
                "company": job.company.id,
                "url": f"https://example.invalid/{fixtures.SOURCE_ID}/{job.job_id}",
                "source_id": job.source_id,
                "minutes": index,
                "category": job.category,
                "level": job.level,
                # psycopg2 adapts a Python list to a Postgres array and None to
                # NULL. The two are NOT interchangeable here and SC-06 is the
                # case that says so: `[]` must land as `'{}'`.
                "subcategories": job.subcategories,
                "source": None if job.subcategories is None else "classify",
            },
        )


def set_reveal_flag(conn: Any, enabled: bool) -> None:
    """Set (or clear) the UI reveal switch.

    `app_settings` has NO seed row by design — an absent key means the code
    default, which is `False`. So "off" is written as a DELETE rather than as
    `false`, which exercises the absent-key path the service actually ships
    with; the explicit-`false` path is covered by flipping it on and off again.
    """
    with conn.cursor() as cur:
        if enabled:
            cur.execute(
                """
                INSERT INTO app_settings (key, value, updated_at, updated_by)
                VALUES (%s, 'true'::jsonb, now(), 'e2e-subcategories')
                ON CONFLICT (key) DO UPDATE
                   SET value = 'true'::jsonb, updated_at = now(),
                       updated_by = 'e2e-subcategories'
                """,
                (REVEAL_FLAG_KEY,),
            )
        else:
            cur.execute("DELETE FROM app_settings WHERE key = %s", (REVEAL_FLAG_KEY,))
    conn.commit()


def reseed(dsn: str = DEFAULT_DSN, *, reveal: bool = True) -> int:
    """Drop and rewrite the fixture corpus. Returns the row count written."""
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            _upsert_companies(cur)
            _delete_fixture_jobs(cur)
            _insert_jobs(cur)
        conn.commit()
        set_reveal_flag(conn, reveal)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM job_listings WHERE source_id = %s",
                (fixtures.SOURCE_ID,),
            )
            written = int(cur.fetchone()["n"])
    finally:
        conn.close()
    if written != len(fixtures.JOBS):
        raise AssertionError(
            f"seed wrote {written} rows, expected {len(fixtures.JOBS)} — the corpus "
            f"and the database disagree, so every case below it is meaningless"
        )
    return written


def assert_taxonomy_seeded(dsn: str = DEFAULT_DSN) -> list[str]:
    """The 17 dimension rows migration 5a7d3e9c1b46 inserts.

    Checked at boot as well as in a case, because a database missing them makes
    the UI tree expand into nothing and every UI case fail for a provisioning
    reason that looks like a product regression.
    """
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM job_subcategories ORDER BY sort_order")
            slugs = [r["slug"] for r in cur.fetchall()]
    finally:
        conn.close()
    if sorted(slugs) != sorted(fixtures.EXPECTED_SUBCATEGORY_SLUGS):
        raise AssertionError(
            f"job_subcategories holds {len(slugs)} slugs {sorted(slugs)}, expected the "
            f"17 in fixtures.EXPECTED_SUBCATEGORY_SLUGS. Re-provision with "
            f"`e2e/run.sh subcategories --refresh-db`."
        )
    return slugs


if __name__ == "__main__":
    reveal_off = "--reveal-off" in sys.argv[1:]
    assert_taxonomy_seeded()
    n = reseed(reveal=not reveal_off)
    print(f"seed: {n} job rows, reveal flag {'OFF' if reveal_off else 'ON'}")
