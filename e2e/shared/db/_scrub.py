"""One-time provisioning scrub for a freshly-cloned jobscraper_e2e (PLAN.md §2, §13).

Run ONCE by ensure_db.sh, directly after `alembic upgrade head`, against a
database nothing has connected to yet. This is DATABASE PROVISIONING, not the
suite's per-test cleanup layer (§8) — it removes what the clone inherited from
the owner's live database before any test runs, so it is allowed to do in bulk
what §8 forbids doing per-test (hand-written `DELETE FROM job_listings`):
there is no owning user to hand this to `remove_owned_company` for (that is
exactly the ownerless-row problem being cleaned up), and the whole point is to
establish a clean baseline before ownership-scoped cleanup even applies.

Two things the clone inherits and both must go, per PLAN.md §11.3 / §13:

1. Every `visibility='user'` row — the owner's live experiments, not fixtures.
   Purged in the same order `remove_owned_company` uses (job_locations ->
   job_tags -> job_enrichment -> job_listings -> company_harvests ->
   scrape_runs -> company_scripts -> user_companies -> companies), just done
   in bulk over every such row instead of one id at a time.
2. `procrastinate_jobs` truncated. Two `custom_discovery` jobs are stuck in
   `todo` and other queues carry jobs stuck in `doing` from a killed worker
   (PLAN.md §11.3) — the e2e worker must start from an empty queue table, not
   resurrect a discovery against a company step 1 above just deleted.
"""

from __future__ import annotations

import sys

import psycopg2
import psycopg2.extras


def _table_exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    row = cur.fetchone()
    return row["oid"] is not None


def scrub(dsn: str) -> None:
    conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    try:
        cur = conn.cursor()

        if _table_exists(cur, "procrastinate_jobs"):
            cur.execute("TRUNCATE procrastinate_jobs RESTART IDENTITY CASCADE")
            print("_scrub: truncated procrastinate_jobs")
        else:
            print("_scrub: procrastinate_jobs does not exist yet — nothing to truncate")

        if not _table_exists(cur, "companies"):
            print("_scrub: companies table does not exist — nothing to scrub")
            conn.commit()
            return

        cur.execute("SELECT id FROM companies WHERE visibility = 'user'")
        user_company_ids = [row["id"] for row in cur.fetchall()]
        print(f"_scrub: found {len(user_company_ids)} visibility='user' companies to purge")

        for company_id in user_company_ids:
            source_id = f"custom:{company_id}"
            cur.execute(
                """
                DELETE FROM job_locations jl
                WHERE jl.job_listing_id IN (
                        SELECT id FROM job_listings WHERE source_id = %s
                    )
                  AND NOT EXISTS (
                        SELECT 1 FROM job_listings o
                        WHERE o.id = jl.job_listing_id AND o.source_id <> %s
                    )
                """,
                (source_id, source_id),
            )
            cur.execute("DELETE FROM job_tags WHERE source_id = %s", (source_id,))
            cur.execute("DELETE FROM job_enrichment WHERE source_id = %s", (source_id,))
            cur.execute("DELETE FROM job_listings WHERE source_id = %s", (source_id,))
            cur.execute(
                "DELETE FROM company_harvests WHERE company_id = %s", (company_id,)
            )
            cur.execute("DELETE FROM scrape_runs WHERE company = %s", (company_id,))
            cur.execute(
                "DELETE FROM company_scripts WHERE company_id = %s", (company_id,)
            )
            cur.execute(
                "DELETE FROM user_companies WHERE company_id = %s", (company_id,)
            )
            cur.execute(
                "DELETE FROM companies WHERE id = %s AND visibility = 'user'",
                (company_id,),
            )

        conn.commit()
        print(f"_scrub: purged {len(user_company_ids)} visibility='user' companies")
    except psycopg2.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    db_name = sys.argv[1] if len(sys.argv) > 1 else "jobscraper_e2e"
    dsn = f"postgresql://postgres:postgres@localhost:5432/{db_name}"
    scrub(dsn)
