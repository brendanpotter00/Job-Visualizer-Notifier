"""Integration test: the recipe-board seed migration (``4c1f8a26d7be``) upgrades,
then DOWNGRADES WITHOUT STRANDING A CORPUS.

Why this file exists rather than another case in ``test_migration_companies.py``:
what it pins is not "the rows arrive", it is what the reverse leaves behind. The
first version of ``downgrade()`` deleted the four ``companies`` rows and their
``company_scripts`` and stopped there — and by then those boards have harvested
~3,000 ``recipe:<id>`` rows into ``job_listings``. Those rows survive with no
company row, which is the exact orphan shape ``services/database``'s guard exists
for: invisible on ``GET /api/jobs`` (INNER JOIN ``companies``) and still served by
``GET /api/jobs/search`` (no join), every one of them OPEN, with nothing left
running that could ever close them.

Both halves are now fixed and both are asserted here and in
``test_visibility_leaks`` (Leak 6e): the migration deletes the job rows in the same
transaction, and the read path fails closed if anything else ever produces the
state.

The conftest ``db_conn`` fixture bootstraps with ``create_all`` + *stamp*, so no
ordinary test executes a migration body. This one runs the real ``alembic upgrade``
/ ``downgrade`` against a freshly created database, mirroring
``test_migration_companies.py``.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

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
RECIPE_PREV_HEAD = "87fe6224b0b5"
SEEDED_IDS = ("atlassian", "github", "oracle", "dell")


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _scalar(conn, sql: str, params: tuple = ()) -> int:
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


def _seed_a_harvested_corpus(conn) -> None:
    """What the ``*/30`` fan-out leaves in the database after a few nights.

    One published board's rows in the ``recipe:`` namespace with every sidecar the
    purge order names, plus a PUBLIC control row that must survive the downgrade
    untouched — a downgrade that over-deletes is its own incident.
    """
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled) "
        "VALUES ('ctrl-pub', 'Control', 'greenhouse', 'ctrl', TRUE)"
    )
    for job_id, company, source_id in (
        ("r-1", "oracle", "recipe:oracle"),
        ("r-2", "oracle", "recipe:oracle"),
        ("r-3", "dell", "recipe:dell"),
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
        "VALUES ('run-oracle-1', 'oracle', now()::text, 'full', 'recipe:oracle', TRUE)"
    )
    cur.execute(
        "INSERT INTO company_harvests "
        "(company_id, run_id, started_at, verdict, oracle_kind) "
        "VALUES ('oracle', 'run-oracle-1', now(), 'UNVERIFIED', 'declared_probed')"
    )
    conn.commit()


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run a migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_recipe_seed_downgrade_strands_no_job_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    roundtrip_db = f"migrate_recipe_{uuid.uuid4().hex[:8]}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    with maint.cursor() as maint_cur:
        maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
        maint_cur.execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()

    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    try:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine

        import api.db_models as _db_models

        # ``create_all`` + stamp the PREVIOUS head, the same bootstrap ``conftest``
        # uses — the Alembic chain predates Alembic and cannot run from empty (see
        # the backend empty-DB boot trap). The seed revision is pure DML, so a
        # model-built schema is exactly what it expects to find.
        engine = create_engine(roundtrip_url)
        _db_models.Base.metadata.create_all(engine, checkfirst=False)
        engine.dispose()

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None
        command.stamp(cfg, RECIPE_PREV_HEAD)

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

            # Oracle's opt-in terminus really made it into the stored JSONB (it is
            # the only boolean in the corpus, and a ``json.dumps``-generated seed
            # would have NameError'd on the bare ``true`` before reaching here).
            assert stored["oracle"]["steps"][1]["stop_on_empty_page"] is True
            # ...and Atlassian kept the ``department`` field map the captured recipe
            # carries; it lands in ``details`` and feeds enrichment.
            assert (
                stored["atlassian"]["steps"][1]["fields"]["department"] == "category"
            )
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
                "SELECT count(*) AS c FROM company_harvests WHERE company_id = 'oracle'",
            ) == 0
            assert _scalar(
                verify, "SELECT count(*) AS c FROM scrape_runs WHERE company = 'oracle'"
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
    finally:
        maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
        maint.autocommit = True
        with maint.cursor() as maint_cur:
            maint_cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (roundtrip_db,),
            )
            maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
        maint.close()
