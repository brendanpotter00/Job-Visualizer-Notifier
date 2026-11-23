"""Write a :mod:`fixtures` group into the section's own JVN database, and read
JVN's side of the result back.

WHY RAW SQL AND NOT A PRODUCT WRITE PATH. The rows this section seeds are what
the scrapers would have written: OPEN jobs with a description and no
enrichment. JVN has no endpoint that creates a job listing (scrapers write the
table directly), and driving a scraper would make every case here depend on a
third-party board. The enricher's contract starts at ``GET /pending``; the seed
stops exactly there. So: raw SQL, fenced by :func:`assertions.connect`'s
database guard (``jobscraper_e2e_enricher`` or nothing), on rows keyed by
``source_id = 'e2e_enricher'`` — the same pattern and the same reasoning as
``subcategories/seed.py``.

TWO THINGS HERE DO TOUCH ROWS THIS SECTION DID NOT WRITE, both in its own
database and both on purpose:

* ``enrichment_ticks`` is cleared on every reseed. Only this section's sandbox
  enricher ever pushes metrics into this database, so every row there is one of
  ours from an earlier case — and EN-03 asserts the tick table holds exactly the
  one tick its case ran.
* Every company except the fixture company is DISABLED. The schema-only clone
  arrives with a handful of enabled ashby/script companies seeded by
  migrations, and the backend's periodic fan-outs (``*/30``) would scrape their
  real boards into this database — rows the enricher would then CLAIM, breaking
  every exact-set assertion and reaching a third-party host. Disabling them
  makes the fan-outs a no-op. :func:`assert_no_foreign_claimable_rows` fails
  loudly if a fan-out got there first (fix: ``--refresh-db``).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
for _p in (str(_REPO_ROOT), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixtures  # noqa: E402

from e2e.shared.db import assertions as db  # noqa: E402

DEFAULT_DSN = os.environ.get(
    "E2E_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e_enricher",
)

#: Child tables and the column each is keyed on (``job_locations`` carries no
#: source_id — see subcategories/seed.py for the incident behind listing these
#: explicitly rather than introspecting).
_CHILD_TABLES = (
    ("job_locations", "job_listing_id"),
    ("job_tags", "source_id"),
    ("job_enrichment", "source_id"),
    ("job_freshness", "source_id"),
)


def _upsert_company(cur: Any) -> None:
    # ats='custom': no fan-out task scrapes a 'custom' row without a recipe, so
    # the fixture company can never pull real jobs into this database.
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
        (fixtures.COMPANY_ID, fixtures.COMPANY_NAME, fixtures.COMPANY_ID),
    )
    cur.execute(
        "UPDATE companies SET enabled = FALSE WHERE id <> %s AND enabled",
        (fixtures.COMPANY_ID,),
    )


def _delete_fixture_rows(cur: Any) -> None:
    cur.execute("SELECT id FROM job_listings WHERE source_id = %s", (fixtures.SOURCE_ID,))
    ids = [r["id"] for r in cur.fetchall()]
    for table, key in _CHILD_TABLES:
        cur.execute("SELECT to_regclass(%s) AS oid", (table,))
        if cur.fetchone()["oid"] is None:
            continue
        if key == "source_id":
            cur.execute(f"DELETE FROM {table} WHERE source_id = %s", (fixtures.SOURCE_ID,))
        elif ids:
            cur.execute(f"DELETE FROM {table} WHERE {key} = ANY(%s)", (ids,))
    cur.execute("DELETE FROM job_listings WHERE source_id = %s", (fixtures.SOURCE_ID,))
    cur.execute("DELETE FROM enrichment_ticks")


def _insert_jobs(cur: Any, jobs: Iterable[fixtures.Job], *, start_minute: int = 0) -> int:
    n = 0
    for offset, job in enumerate(jobs):
        # first_seen_at one minute apart, newest first in fixture order, so the
        # /pending claim order (title tier, then first_seen_at DESC) is stable.
        cur.execute(
            """
            INSERT INTO job_listings (
                id, title, company, location, url, source_id, details,
                posted_on, created_at, status, has_matched, ai_metadata,
                first_seen_at, details_scraped, normalization_status,
                enrichment_status
            ) VALUES (
                %(id)s, %(title)s, %(company)s, %(location)s, %(url)s, %(source_id)s,
                %(details)s::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                now() - (%(minutes)s || ' minutes')::interval,
                'OPEN', FALSE, '{}'::jsonb,
                now() - (%(minutes)s || ' minutes')::interval,
                TRUE, 'done', NULL
            )
            """,
            {
                "id": job.job_id,
                "title": job.title,
                "company": fixtures.COMPANY_ID,
                "location": job.location,
                "url": f"https://example.invalid/{fixtures.SOURCE_ID}/{job.job_id}",
                "source_id": fixtures.SOURCE_ID,
                # description_html is the first key DESCRIPTION_SQL coalesces,
                # so /pending's "must have a description" guard admits the row.
                "details": json.dumps({"description_html": job.description_html}),
                "minutes": start_minute + offset,
            },
        )
        n += 1
    return n


def reseed(jobs: Iterable[fixtures.Job], dsn: str = DEFAULT_DSN) -> int:
    """Drop every fixture row (and every pushed tick), then write ``jobs`` as
    OPEN, described, never-enriched listings. Returns the rows written."""
    jobs = tuple(jobs)
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            _upsert_company(cur)
            _delete_fixture_rows(cur)
            written = _insert_jobs(cur, jobs)
        conn.commit()
    finally:
        conn.close()
    assert_no_foreign_claimable_rows(dsn)
    if written != len(jobs):
        raise AssertionError(f"seed wrote {written} rows, expected {len(jobs)}")
    return written


def add_jobs(jobs: Iterable[fixtures.Job], dsn: str = DEFAULT_DSN) -> int:
    """Write more rows WITHOUT clearing the ones already there (EN-09's second
    group, which must land beside the first)."""
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            written = _insert_jobs(cur, jobs, start_minute=100)
        conn.commit()
    finally:
        conn.close()
    return written


def assert_no_foreign_claimable_rows(dsn: str = DEFAULT_DSN) -> None:
    """A schema-only database holds no jobs but ours. A claimable row from any
    other source means a backend fan-out scraped a real board into it, and the
    enricher would claim it — failing every exact-set case for a reason that
    looks like an enricher bug. Say so here instead."""
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, count(*) AS n FROM job_listings "
                "WHERE source_id <> %s AND status = 'OPEN' AND enrichment_status IS NULL "
                "GROUP BY source_id",
                (fixtures.SOURCE_ID,),
            )
            foreign = {r["source_id"]: int(r["n"]) for r in cur.fetchall()}
    finally:
        conn.close()
    if foreign:
        raise AssertionError(
            f"jobscraper_e2e_enricher holds claimable rows from other sources {foreign}; "
            f"a backend fan-out scraped a real board into it before the seed disabled "
            f"the companies. Re-provision with `e2e/run.sh enricher --refresh-db`."
        )


# --- provisioning: the source clone's known drift -----------------------------

TAXONOMY_ARTIFACT = _REPO_ROOT / "src" / "backend" / "taxonomy.json"


def repair_known_drift(dsn: str = DEFAULT_DSN) -> list[str]:
    """Bring this section's database up to what the migrations would have made.

    ``ensure_db.sh --schema-only`` clones ``jobscraper_pr243``, and that local
    source is DRIFTED: its ``alembic_version`` is stamped past migrations whose
    effects it does not have (measured 2026-11-23, and the same in every local
    ``jobscraper*`` database). For the enricher's write path that is fatal, not
    cosmetic:

    * ``job_listings.search_text`` / ``primary_country`` are missing (migration
      ``e3b1a4c9d7f2``), and ``apply_result`` recomputes ``search_text`` on every
      row it writes — so EVERY ``/results`` item fails with UndefinedColumn;
    * ``job_categories`` lacks ``data_scientist`` and ``job_levels`` lacks
      ``intern`` (seeded by ``0fa33aca5bda`` / ``0b61e444ea25``), so a
      correctly-classified data-science row FK-fails.

    The repair is idempotent and scoped to THIS database (``assertions.connect``
    refuses any other): the two columns are added exactly as the migration
    declares them (nullable text, no default), and the two dimension tables are
    upserted from ``src/backend/taxonomy.json`` — JVN's generated taxonomy
    artifact, read here, never re-typed. Returns what it changed, so the drift
    is printed rather than silently absorbed. A section-local repair, on
    purpose: changing ``ensure_db.sh`` would change every other section's
    database too.
    """
    artifact = json.loads(TAXONOMY_ARTIFACT.read_text(encoding="utf-8"))
    changes: list[str] = []
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            for column in ("search_text", "primary_country"):
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'job_listings' "
                    "AND column_name = %s",
                    (column,),
                )
                if cur.fetchone() is None:
                    cur.execute(f"ALTER TABLE job_listings ADD COLUMN IF NOT EXISTS {column} text")
                    changes.append(f"added job_listings.{column}")
            for row in artifact["categories"]:
                cur.execute(
                    "INSERT INTO job_categories (slug, label, sort_order) VALUES (%s, %s, %s) "
                    "ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, "
                    "sort_order = EXCLUDED.sort_order "
                    "WHERE (job_categories.label, job_categories.sort_order) "
                    "IS DISTINCT FROM (EXCLUDED.label, EXCLUDED.sort_order) "
                    "RETURNING slug",
                    (row["slug"], row["label"], row["sort_order"]),
                )
                if cur.fetchone() is not None:
                    changes.append(f"upserted job_categories.{row['slug']}")
            # Parents before children: the self-FK needs `entry` before `new_grad`.
            levels = sorted(artifact["levels"], key=lambda r: r["parent_slug"] is not None)
            for row in levels:
                cur.execute(
                    "INSERT INTO job_levels (slug, label, rank, parent_slug) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, rank = EXCLUDED.rank, "
                    "parent_slug = EXCLUDED.parent_slug "
                    "WHERE (job_levels.label, job_levels.rank, job_levels.parent_slug) "
                    "IS DISTINCT FROM (EXCLUDED.label, EXCLUDED.rank, EXCLUDED.parent_slug) "
                    "RETURNING slug",
                    (row["slug"], row["label"], row["sort_order"], row["parent_slug"]),
                )
                if cur.fetchone() is not None:
                    changes.append(f"upserted job_levels.{row['slug']}")
        conn.commit()
    finally:
        conn.close()
    return changes


# --- JVN-side readers ------------------------------------------------------


def listings(conn: Any, ids: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, enrichment_status, enrichment_category, enrichment_level, "
            "enrichment_subcategories, enrichment_subcategory_source, enrichment_claimed_at "
            "FROM job_listings WHERE source_id = %s",
            (fixtures.SOURCE_ID,),
        )
        rows = {r["id"]: dict(r) for r in cur.fetchall()}
    if ids is not None:
        wanted = set(ids)
        rows = {k: v for k, v in rows.items() if k in wanted}
    return rows


def enrichments(conn: Any) -> dict[str, dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM job_enrichment WHERE source_id = %s", (fixtures.SOURCE_ID,)
        )
        return {r["job_listing_id"]: dict(r) for r in cur.fetchall()}


def tags(conn: Any) -> dict[str, list[str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT job_listing_id, tag FROM job_tags WHERE source_id = %s "
            "ORDER BY job_listing_id, tag",
            (fixtures.SOURCE_ID,),
        )
        out: dict[str, list[str]] = {}
        for r in cur.fetchall():
            out.setdefault(r["job_listing_id"], []).append(r["tag"])
        return out


def ticks(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM enrichment_ticks ORDER BY received_at")
        return [dict(r) for r in cur.fetchall()]


if __name__ == "__main__":
    if sys.argv[1:2] == ["--repair"]:
        done = repair_known_drift()
        print("seed: drift repair — " + ("; ".join(done) if done else "nothing to repair"))
        raise SystemExit(0)
    group = sys.argv[1] if len(sys.argv) > 1 else "EN01"
    n = reseed(fixtures.GROUPS[group])
    print(f"seed: {n} rows of group {group} in {DEFAULT_DSN.rsplit('/', 1)[-1]}")
