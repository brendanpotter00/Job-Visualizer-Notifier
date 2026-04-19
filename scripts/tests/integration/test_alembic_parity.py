"""
Integration test: prove db_models.py is a faithful mirror of the post-0005 schema.

How it works
------------
1. Create a throwaway PostgreSQL database (e.g. `parity_test_<hex>`) on the
   local server — gives us a clean namespace where autogenerate sees only the
   tables produced by the old runner, with no contamination from other envs
   cohabiting on `jobscraper` (e.g. `*_local` tables or stray `*_test_<hex>`
   tables from prior test runs).
2. Apply the OLD runner (`migrate_up`) against the fresh DB to build the
   post-0005 schema.
3. Stamp Alembic's baseline revision into `alembic_version_<test_env>`.
4. Invoke `alembic revision --autogenerate --message parity_check` against
   the same DB.
5. Parse the resulting revision file with `ast`. Assert every top-level
   statement inside `upgrade()` is `pass` / a docstring / a bare comment
   expression. Any `op.*` call means `db_models.py` drifts from the real
   schema — fail with the full generated file dumped into the assertion
   message so the drift is visible.
6. Tear down: drop the generated revision file and drop the throwaway DB.

This test is a fail-loud canary. If it ever fails, the fix is in
`src/backend/api/db_models.py`, not in the baseline revision or env.py.
"""

from __future__ import annotations

import ast
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

# Worktree / repo-root detection. This test file lives at
# <repo>/scripts/tests/integration/test_alembic_parity.py.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_VERSIONS_DIR = _REPO_ROOT / "src" / "backend" / "alembic" / "versions"

# Make `scripts.shared.*` importable (mirrors scripts/tests/conftest.py pattern).
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Also ensure src/backend is importable so api.* modules resolve when Alembic's
# env.py does `from api.config import settings`.
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


def _swap_db_name(url: str, new_db: str) -> str:
    """Return `url` with its path replaced by `/<new_db>`."""
    parts = urlparse(url)
    return urlunparse(parts._replace(path=f"/{new_db}"))


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run parity test against a prod-like TEST_DATABASE_URL",
)
def test_autogen_against_fresh_post_0005_schema_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autogen must produce no `op.*` calls when db_models.py matches the old runner's schema."""
    test_env = f"test_{uuid.uuid4().hex[:8]}"
    parity_db_name = f"parity_{test_env}"
    parity_db_url = _swap_db_name(TEST_DB_URL, parity_db_name)

    # Create the throwaway DB via the postgres maintenance DB. Using autocommit
    # because CREATE DATABASE can't run inside a transaction.
    admin_url = _swap_db_name(TEST_DB_URL, "postgres")
    admin_conn = psycopg2.connect(admin_url)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{parity_db_name}"')
    admin_conn.close()

    generated_path: Path | None = None
    conn: psycopg2.extensions.connection | None = None
    try:
        # Alembic's env.py imports api.config.Settings() at module import time.
        # The Settings validator rejects scraper_environment values outside
        # {"local","qa","prod"}, so we can't just set SCRAPER_ENVIRONMENT to a
        # test_<hex> value — pydantic would raise. Workaround: import api.config
        # with a valid env first, extend its ALLOWED_ENVIRONMENTS to include our
        # test env, then rebuild the module-level settings singleton so env.py's
        # `from api.config import settings` sees a Settings built with the test
        # env. Entirely in-process; does not modify the file on disk.
        monkeypatch.setenv("DATABASE_URL", parity_db_url)
        monkeypatch.setenv("SCRAPER_ENVIRONMENT", "local")  # valid, temporary

        import api.config as _api_config  # noqa: WPS433 — intentional lazy import

        monkeypatch.setattr(
            _api_config,
            "ALLOWED_ENVIRONMENTS",
            _api_config.ALLOWED_ENVIRONMENTS | {test_env},
        )
        monkeypatch.setenv("SCRAPER_ENVIRONMENT", test_env)
        # Rebuild the module-level settings singleton so env.py sees the test env
        # and the throwaway DB URL.
        monkeypatch.setattr(_api_config, "settings", _api_config.Settings())

        # Defer alembic imports until settings are fixed up.
        from alembic import command  # noqa: WPS433
        from alembic.config import Config  # noqa: WPS433

        from shared.migrations.runner import migrate_up  # old runner

        # 1) Create the post-0005 schema via the OLD runner, against the
        #    throwaway DB (NOT against TEST_DB_URL).
        conn = psycopg2.connect(parity_db_url, cursor_factory=RealDictCursor)
        applied = migrate_up(conn, test_env)
        assert applied, f"old runner applied no migrations for env={test_env}"

        # Drop the old runner's bookkeeping table — it isn't part of the
        # post-0005 target schema that db_models.py is supposed to mirror
        # (Unit 6 will delete the runner entirely). Leaving it in the DB would
        # make autogenerate emit a spurious op.drop_table('schema_migrations_*')
        # that isn't real model drift.
        with conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "schema_migrations_{test_env}" CASCADE')
        conn.commit()

        # 2) Configure Alembic against the throwaway DB and stamp baseline.
        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", parity_db_url)
        command.stamp(cfg, "head")

        # 3) Run autogenerate. Alembic will write a new revision file under
        #    src/backend/alembic/versions/ named *_parity_check.py.
        command.revision(cfg, autogenerate=True, message="parity_check")

        # 4) Find the generated file.
        candidates = sorted(_VERSIONS_DIR.glob("*_parity_check.py"))
        assert (
            len(candidates) == 1
        ), f"expected exactly one parity_check revision, found {candidates}"
        generated_path = candidates[0]

        # Parse upgrade() body. Allowed statements:
        #   * a docstring (ast.Expr wrapping ast.Constant of str)
        #   * `pass`
        # Anything else (op.create_table, op.add_column, etc.) is drift.
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
                # docstring
                continue
            offending.append(ast.unparse(stmt))

        if offending:
            pytest.fail(
                "Autogenerate produced DDL — db_models.py drifts from the post-0005 "
                "schema.\n\nOffending statements:\n  - "
                + "\n  - ".join(offending)
                + "\n\nFull generated file:\n"
                + src
            )

    finally:
        # Teardown: drop generated revision file first so a failing test in a
        # later run doesn't pick it up.
        if generated_path is not None and generated_path.exists():
            generated_path.unlink()
        # Also nuke any stray parity_check files (belt + suspenders).
        for stray in _VERSIONS_DIR.glob("*_parity_check.py"):
            stray.unlink()

        # Close the main connection before dropping the DB.
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

        # Drop the throwaway DB via the maintenance DB.
        try:
            admin_conn = psycopg2.connect(admin_url)
            admin_conn.autocommit = True
            with admin_conn.cursor() as cur:
                # Terminate any lingering connections to the throwaway DB so
                # DROP DATABASE isn't blocked.
                cur.execute(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (parity_db_name,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{parity_db_name}"')
            admin_conn.close()
        except Exception:
            # Best-effort; don't mask the test's primary failure (if any).
            pass
