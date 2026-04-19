"""
Integration test: Alembic autogenerate is stable against Base.metadata.create_all.

Run this test against a freshly-materialized schema built by
`Base.metadata.create_all(engine)`. Stamp Alembic's baseline so
`alembic_version_<env>` is populated, then run autogenerate and assert the
generated `upgrade()` body contains no `op.*` calls.

If this test fails, it means `Base.metadata.create_all` and Alembic's
autogenerate disagree about some aspect of the schema — a check constraint,
an index name, a server_default, a type precision — and the next real
autogenerate revision will include reconciliation DDL as a result. Fix by
editing `src/backend/api/db_models.py` (not the baseline revision) until
the diff is empty.

Created in Unit 3, rewritten in Unit 6 after the old runner was deleted.
"""

from __future__ import annotations

import ast
import importlib
import logging
import os
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

# Path setup. scripts/tests/integration/test_alembic_parity.py →
# parents[3] is the worktree root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"
_SRC_BACKEND = _REPO_ROOT / "src" / "backend"

if str(_SRC_BACKEND) not in sys.path:
    sys.path.insert(0, str(_SRC_BACKEND))

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper",
)


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


@pytest.mark.xfail(
    strict=False,
    reason=(
        "envAgnosticTables Unit 2: db_models.py is unsuffixed but live tables "
        "are still _local-suffixed until Unit 3's rename migration applies. "
        "Unit 3 removes this xfail."
    ),
)
@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run parity test against a prod-like TEST_DATABASE_URL",
)
def test_autogen_against_create_all_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autogenerate must produce no `op.*` calls when schema was built via create_all."""
    test_env = f"test_{uuid.uuid4().hex[:8]}"
    parity_db = f"parity_{test_env}"

    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL.rsplit("/", 1)[0] + f"/{parity_db}")
    # Set SCRAPER_ENVIRONMENT to a valid value first so api.config's module-level
    # `settings = Settings()` succeeds at import time. We then widen
    # ALLOWED_ENVIRONMENTS in-process, flip the env var to our test value, and
    # rebuild the singleton so env.py sees the test env.
    monkeypatch.setenv("SCRAPER_ENVIRONMENT", "local")

    import api.config as _api_config
    monkeypatch.setattr(
        _api_config,
        "ALLOWED_ENVIRONMENTS",
        _api_config.ALLOWED_ENVIRONMENTS | {test_env},
    )
    monkeypatch.setenv("SCRAPER_ENVIRONMENT", test_env)
    monkeypatch.setattr(_api_config, "settings", _api_config.Settings())

    # Reload db_models so Base's table names resolve to the test env.
    import api.db_models
    importlib.reload(api.db_models)
    from api.db_models import Base

    # Create the parity DB from the `postgres` maintenance DB so we get a
    # clean namespace (the shared jobscraper DB has leftover *_local tables
    # that would pollute autogenerate's comparison).
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint_cur = maint.cursor()
    maint_cur.execute(
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (parity_db,),
    )
    maint_cur.execute(f'DROP DATABASE IF EXISTS "{parity_db}"')
    maint_cur.execute(f'CREATE DATABASE "{parity_db}"')
    maint.close()

    parity_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{parity_db}"
    generated_path: Path | None = None

    try:
        # 1) Build the schema via create_all.
        from sqlalchemy import create_engine
        engine = create_engine(parity_url)
        Base.metadata.create_all(engine)
        engine.dispose()

        # 2) Stamp Alembic baseline.
        from alembic import command  # lazy import after env vars
        from alembic.config import Config
        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", parity_url)
        cfg.set_main_option(
            "script_location", str(_REPO_ROOT / "src" / "backend" / "alembic")
        )
        cfg.config_file_name = None  # skip fileConfig (mirrors migrations.py)
        command.stamp(cfg, "head")

        # 3) Run autogenerate.
        command.revision(cfg, autogenerate=True, message="parity_check")

        # 4) Find generated revision file.
        candidates = sorted(_VERSIONS_DIR.glob("*_parity_check.py"))
        assert (
            len(candidates) == 1
        ), f"expected exactly one parity_check revision, found {candidates}"
        generated_path = candidates[0]

        # 5) Parse upgrade() body; assert empty modulo pass/docstring.
        src = generated_path.read_text()
        tree = ast.parse(src)
        upgrade_fn = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"),
            None,
        )
        assert upgrade_fn is not None, "generated revision missing upgrade()"

        offending: list[str] = []
        for stmt in upgrade_fn.body:
            if isinstance(stmt, ast.Pass):
                continue
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                continue
            offending.append(ast.unparse(stmt))

        if offending:
            pytest.fail(
                "Autogenerate produced DDL — Base.metadata.create_all and Alembic "
                "autogenerate disagree about the schema. Fix db_models.py until the "
                "diff is empty.\n\nOffending statements:\n  - "
                + "\n  - ".join(offending)
                + "\n\nFull generated file:\n"
                + src
            )

    finally:
        # Drop generated revision file first so a failing test in a later run
        # doesn't pick it up.
        if generated_path is not None and generated_path.exists():
            generated_path.unlink()
        for stray in _VERSIONS_DIR.glob("*_parity_check.py"):
            stray.unlink()

        # Drop the parity DB from the maintenance DB. Teardown must keep
        # going past a failure (so db_models reload below still runs), but
        # the failure must NOT be silent — leaked databases compound across
        # CI runs and the 2026-04-19 volume incident is the consequence.
        try:
            maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
            maint.autocommit = True
            maint_cur = maint.cursor()
            # Terminate any lingering connections to the parity DB so DROP isn't blocked.
            maint_cur.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (parity_db,),
            )
            maint_cur.execute(f'DROP DATABASE IF EXISTS "{parity_db}"')
            maint.close()
        except Exception as drop_exc:
            logging.getLogger(__name__).error(
                "Failed to drop parity test database %s during teardown: %s",
                parity_db,
                drop_exc,
            )

        # Restore db_models to its original env so sibling tests aren't surprised.
        os.environ["SCRAPER_ENVIRONMENT"] = "local"
        importlib.reload(api.db_models)
