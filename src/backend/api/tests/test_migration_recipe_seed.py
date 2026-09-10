"""Integration test: the recipe-board seed migration (``4c1f8a26d7be``) upgrades,
then DOWNGRADES WITHOUT STRANDING A CORPUS — and without touching rows it never
created.

Why this file exists rather than another case in ``test_migration_companies.py``:
what it pins is not "the rows arrive", it is what the reverse leaves behind. Two
separate ways the reverse can be wrong, one test each:

1. **Under-deleting.** The first version of ``downgrade()`` deleted the
   ``companies`` rows and their ``company_scripts`` and stopped there — and by then
   those boards have harvested hundreds of ``recipe:<id>`` rows into
   ``job_listings``. Those rows survive with no company row, which is the exact
   orphan shape ``services/database``'s guard exists for: invisible on
   ``GET /api/jobs`` (INNER JOIN ``companies``) and still served by
   ``GET /api/jobs/search`` (no join), every one of them OPEN, with nothing left
   running that could ever close them.

2. **Over-deleting.** ``upgrade()`` inserts ``ON CONFLICT (id) DO NOTHING``, so on a
   database where one of these ids is already taken the migration is a partial
   no-op — and a ``downgrade()`` that deleted by bare id would then destroy a
   company, and its whole harvested corpus, that this migration never created.

Both halves are fixed and both are asserted here (and the orphan read path in
``test_visibility_leaks``, Leak 6e).

The conftest ``db_conn`` fixture bootstraps with ``create_all`` + *stamp*, so no
ordinary test executes a migration body. These run the real ``alembic upgrade`` /
``downgrade`` against a freshly created database, mirroring
``test_migration_companies.py``.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Iterator

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_SCRIPT_LOCATION = _REPO_ROOT / "src" / "backend" / "alembic"
_SRC_BACKEND = _REPO_ROOT / "src" / "backend"

if str(_SRC_BACKEND) not in sys.path:
    sys.path.insert(0, str(_SRC_BACKEND))

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper",
)

RECIPE_SEED_REV = "4c1f8a26d7be"
RECIPE_PREV_HEAD = "e3b1a4c9d7f2"
SEEDED_IDS = ("atlassian", "github")


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


_SKIP_PROD_LIKE = pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run a migration roundtrip against a prod-like TEST_DATABASE_URL",
)


def _scalar(conn, sql: str, params: tuple = ()) -> int:
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


@pytest.fixture
def staged(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[object, str]]:
    """A throwaway database, schema built and stamped at the revision BEFORE the seed.

    ``create_all`` + stamp is the same bootstrap ``conftest`` uses — the Alembic
    chain predates Alembic and cannot run from empty (see the backend empty-DB boot
    trap). The seed revision is pure DML, so a model-built schema is exactly what it
    expects to find.

    Yields ``(alembic_config, database_url)``; the database is dropped on teardown.
    """
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    db_name = f"migrate_recipe_{uuid.uuid4().hex[:8]}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    with maint.cursor() as maint_cur:
        maint_cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        maint_cur.execute(f'CREATE DATABASE "{db_name}"')
    maint.close()

    url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{db_name}"

    try:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        import api.db_models as _db_models

        engine = create_engine(url)
        _db_models.Base.metadata.create_all(engine, checkfirst=False)
        engine.dispose()

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None
        command.stamp(cfg, RECIPE_PREV_HEAD)

        yield cfg, url
    finally:
        maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
        maint.autocommit = True
        with maint.cursor() as maint_cur:
            maint_cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            maint_cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        maint.close()


def _seed_a_harvested_corpus(conn) -> None:
    """What the ``*/30`` fan-out leaves in the database after a few nights.

    Both published boards' rows in the ``recipe:`` namespace with every sidecar the
    purge order names, plus a PUBLIC control row that must survive the downgrade
    untouched — a downgrade that over-deletes is its own incident.
    """
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled) "
        "VALUES ('ctrl-pub', 'Control', 'greenhouse', 'ctrl', TRUE)"
    )
    for job_id, company, source_id in (
        ("r-1", "atlassian", "recipe:atlassian"),
        ("r-2", "atlassian", "recipe:atlassian"),
        ("r-3", "github", "recipe:github"),
        ("c-1", "ctrl-pub", "greenhouse_api"),
    ):
        cur.execute(
            "INSERT INTO job_listings "
            "(id, title, company, url, source_id, created_at, first_seen_at, status) "
            "VALUES (%s, 'Engineer', %s, 'https://x/1', %s, now(), now(), 'OPEN')",
            (job_id, company, source_id),
        )
        cur.execute(
            "INSERT INTO job_tags (source_id, job_listing_id, tag) VALUES (%s, %s, 'k8s')",
            (source_id, job_id),
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id) VALUES (%s, %s)",
            (source_id, job_id),
        )
    cur.execute(
        "INSERT INTO locations (canonical_name, kind, city, region, country) "
        "VALUES ('Testville, ZZ', 'city', 'Testville', 'ZZ', 'US') RETURNING id"
    )
    row = cur.fetchone()
    location_id = int(row["id"] if isinstance(row, dict) else row[0])
    for job_id in ("r-1", "c-1"):
        cur.execute(
            "INSERT INTO job_locations (job_listing_id, normalized_location_id, is_primary) "
            "VALUES (%s, %s, TRUE)",
            (job_id, location_id),
        )
    cur.execute(
        "INSERT INTO scrape_runs (run_id, company, started_at, mode, source_id, success) "
        "VALUES ('run-atlassian-1', 'atlassian', now()::text, 'full', "
        "'recipe:atlassian', TRUE)"
    )
    cur.execute(
        "INSERT INTO company_harvests "
        "(company_id, run_id, started_at, verdict, oracle_kind) "
        "VALUES ('atlassian', 'run-atlassian-1', now(), 'VERIFIED', 'none')"
    )
    conn.commit()


@_SKIP_PROD_LIKE
def test_recipe_seed_downgrade_strands_no_job_rows(staged) -> None:
    from alembic import command

    cfg, roundtrip_url = staged

    command.upgrade(cfg, RECIPE_SEED_REV)

    verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        assert _scalar(
            verify, "SELECT count(*) AS c FROM companies WHERE ats = 'recipe'"
        ) == len(SEEDED_IDS)
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM company_scripts WHERE company_id = ANY(%s)",
            (list(SEEDED_IDS),),
        ) == len(SEEDED_IDS)

        # The stored script is the committed fixture, byte for byte — the
        # migration is generated FROM those files and drifting is the bug.
        cur = verify.cursor()
        cur.execute(
            "SELECT company_id, script FROM company_scripts "
            "WHERE company_id = ANY(%s)",
            (list(SEEDED_IDS),),
        )
        stored = {r["company_id"]: r["script"] for r in cur.fetchall()}
        fixtures = Path(__file__).parent / "fixtures" / "recipes" / "published"
        for company_id in SEEDED_IDS:
            expected = json.loads((fixtures / f"{company_id}.json").read_text())
            assert stored[company_id] == expected, company_id

        # Atlassian kept the ``department`` field map the captured recipe carries;
        # it lands in ``details`` and feeds enrichment.
        assert stored["atlassian"]["steps"][1]["fields"]["department"] == "category"
        # GitHub's sweep really is a paginated one in the stored JSONB.
        assert stored["github"]["steps"][1]["op"] == "paginate_page"
    finally:
        verify.close()

    harvested = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        _seed_a_harvested_corpus(harvested)
        assert _scalar(
            harvested,
            "SELECT count(*) AS c FROM job_listings "
            "WHERE starts_with(source_id, 'recipe:')",
        ) == 3
    finally:
        harvested.close()

    command.downgrade(cfg, RECIPE_PREV_HEAD)

    verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        assert _scalar(
            verify, "SELECT count(*) AS c FROM companies WHERE ats = 'recipe'"
        ) == 0
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM company_scripts WHERE company_id = ANY(%s)",
            (list(SEEDED_IDS),),
        ) == 0

        # THE ASSERTION THIS FILE EXISTS FOR.
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM job_listings "
            "WHERE starts_with(source_id, 'recipe:')",
        ) == 0, (
            "the downgrade stranded a published recipe corpus — job rows with "
            "no companies row, still OPEN, still served by /api/jobs/search"
        )
        for table in ("job_tags", "job_enrichment"):
            assert _scalar(
                verify,
                f"SELECT count(*) AS c FROM {table} "
                "WHERE starts_with(source_id, 'recipe:')",
            ) == 0, table
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM job_locations WHERE job_listing_id = 'r-1'",
        ) == 0
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM job_freshness "
            "WHERE starts_with(source_id, 'recipe:')",
        ) == 0, "job_freshness should have CASCADEd off job_listings"
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM company_harvests WHERE company_id = 'atlassian'",
        ) == 0
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM scrape_runs WHERE company = 'atlassian'",
        ) == 0

        # CONTROL: the public corpus is untouched. A downgrade that over-deletes
        # is its own incident.
        assert _scalar(
            verify, "SELECT count(*) AS c FROM job_listings WHERE id = 'c-1'"
        ) == 1
        assert _scalar(
            verify, "SELECT count(*) AS c FROM job_locations "
            "WHERE job_listing_id = 'c-1'"
        ) == 1
        assert _scalar(
            verify, "SELECT count(*) AS c FROM companies WHERE id = 'ctrl-pub'"
        ) == 1
    finally:
        verify.close()

    # Re-upgrade: the seed is repeatable after its own reverse.
    command.upgrade(cfg, RECIPE_SEED_REV)
    verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        assert _scalar(
            verify, "SELECT count(*) AS c FROM companies WHERE ats = 'recipe'"
        ) == len(SEEDED_IDS)
    finally:
        verify.close()


@_SKIP_PROD_LIKE
def test_downgrade_spares_a_company_the_upgrade_did_not_create(staged) -> None:
    """The ``ON CONFLICT DO NOTHING`` half: what the migration skips, it must not delete.

    ``upgrade()`` inserts the company and its script under SEPARATE
    ``ON CONFLICT``s, so on a database where one of these ids is already taken the
    two halves diverge: the company insert is a no-op, the script insert is not. A
    ``downgrade()`` that deleted by bare id would then take out somebody else's
    company row — and, worse, the entire job corpus hanging off it.

    Here ``github`` already exists as a GREENHOUSE company with its own jobs. After
    upgrade + downgrade the only thing that may have moved is the
    ``company_scripts`` row the migration genuinely did insert.
    """
    from alembic import command

    cfg, roundtrip_url = staged

    pre = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        cur = pre.cursor()
        cur.execute(
            "INSERT INTO companies (id, display_name, ats, board_token, enabled) "
            "VALUES ('github', 'GitHub (someone else''s row)', 'greenhouse', "
            "'githubinc', TRUE)"
        )
        cur.execute(
            "INSERT INTO job_listings "
            "(id, title, company, url, source_id, created_at, first_seen_at, status) "
            "VALUES ('gh-1', 'Engineer', 'github', 'https://x/1', 'greenhouse_api', "
            "now(), now(), 'OPEN')"
        )
        pre.commit()
    finally:
        pre.close()

    command.upgrade(cfg, RECIPE_SEED_REV)

    verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        # The company insert conflicted and did nothing; the script insert did not.
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM companies WHERE id = 'github' "
            "AND ats = 'greenhouse'",
        ) == 1
        assert _scalar(
            verify, "SELECT count(*) AS c FROM company_scripts WHERE company_id = 'github'"
        ) == 1
        # ...and atlassian, whose id was free, was seeded normally.
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM companies WHERE id = 'atlassian' "
            "AND ats = 'recipe'",
        ) == 1
    finally:
        verify.close()

    # A few nights of harvesting under the pre-existing greenhouse row.
    harvested = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        cur = harvested.cursor()
        cur.execute(
            "INSERT INTO job_listings "
            "(id, title, company, url, source_id, created_at, first_seen_at, status) "
            "VALUES ('gh-2', 'Engineer', 'github', 'https://x/2', 'greenhouse_api', "
            "now(), now(), 'OPEN')"
        )
        cur.execute(
            "INSERT INTO scrape_runs (run_id, company, started_at, mode, source_id, success) "
            "VALUES ('run-gh-1', 'github', now()::text, 'full', 'greenhouse_api', TRUE)"
        )
        cur.execute(
            "INSERT INTO company_harvests "
            "(company_id, run_id, started_at, verdict, oracle_kind) "
            "VALUES ('github', 'run-gh-1', now(), 'VERIFIED', 'none')"
        )
        harvested.commit()
    finally:
        harvested.close()

    command.downgrade(cfg, RECIPE_PREV_HEAD)

    verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
    try:
        # THE ASSERTIONS THIS TEST EXISTS FOR — the row the migration skipped, and
        # everything hanging off it, survives its reverse.
        assert _scalar(
            verify,
            "SELECT count(*) AS c FROM companies WHERE id = 'github' "
            "AND ats = 'greenhouse'",
        ) == 1, "downgrade deleted a company row the upgrade never created"
        assert _scalar(
            verify, "SELECT count(*) AS c FROM job_listings WHERE company = 'github'"
        ) == 2, "downgrade deleted job rows belonging to someone else's company"
        assert _scalar(
            verify, "SELECT count(*) AS c FROM scrape_runs WHERE company = 'github'"
        ) == 1, "downgrade deleted operational rows it never wrote"
        assert _scalar(
            verify, "SELECT count(*) AS c FROM company_harvests WHERE company_id = 'github'"
        ) == 1, "downgrade deleted harvest audit rows it never wrote"

        # The one row it DID insert is the one row it takes back.
        assert _scalar(
            verify, "SELECT count(*) AS c FROM company_scripts WHERE company_id = 'github'"
        ) == 0

        # And the company it really did create is fully gone.
        assert _scalar(
            verify, "SELECT count(*) AS c FROM companies WHERE id = 'atlassian'"
        ) == 0
    finally:
        verify.close()
