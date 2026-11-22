"""Integration test: the North Star migration (`bcbc67dbd87e`) round-trips.

Modelled on test_migration_user_saved_filters_subcategory.py: build the
pre-migration shape of `users` + `user_visits` in a fresh database, seed a
small cohort with known visit patterns, stamp the parent revision, upgrade
through THIS revision, then check the new columns, the internal-account flag,
and every number the three `metrics` views produce. Downgrade and assert the
schema, views and columns are gone.

The view assertions are the point: they pin the USER-METRICS.md definitions
(day 3-30 / 7-30 windows, weeks 1-8, the 14-day comeback, the 2026-06-25
cohort start, internal accounts excluded) to hand-computed values.
"""

from __future__ import annotations

import os
import sys
import uuid
from decimal import Decimal
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

_PRIOR_HEAD = "61434ebb0689"
_NORTH_STAR_REV = "bcbc67dbd87e"

# Monday; every cohort user signs up at the start of this week.
_SIGNUP = "2026-07-06T00:00:00+00:00"


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _column(conn, table: str, column: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()


def _seed(conn) -> None:
    cur = conn.cursor()

    def user(uid: str, email: str, created_at: str) -> None:
        cur.execute(
            "INSERT INTO users (id, auth0_id, email, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (uid, f"auth0|{uid}", email, created_at, created_at),
        )

    def visit(uid: str, days_after: float, signup: str = _SIGNUP) -> None:
        cur.execute(
            "INSERT INTO user_visits (user_id, visited_at) "
            "VALUES (%s, %s::timestamptz + make_interval(secs => %s))",
            (uid, signup, days_after * 86400),
        )

    # back day 3+ and 7+, weeks 1 and 2, no gap between visits.
    user("ua", "a@x.io", _SIGNUP)
    for d in (1, 4, 8, 20):
        visit("ua", d)
    # Only a day-2 visit: counts toward nothing.
    user("ub", "b@x.io", _SIGNUP)
    visit("ub", 2)
    # Day 40 is outside both return windows but is week 5 and a comeback
    # after a 39-day gap.
    user("uc", "c@x.io", _SIGNUP)
    visit("uc", 1)
    visit("uc", 40)
    # Internal: flagged by the migration, so excluded everywhere.
    user("uint", "brendanpotter00@gmail.com", _SIGNUP)
    visit("uint", 10)
    # The prod test account is NOT internal (owner's call) — it must not be
    # flagged. It signed up before 2026-06-25 (user_visits starts the 24th), so
    # the cohort start excludes it here, not the flag.
    user("uold", "nonadmin@nonadmin.com", "2026-06-20T00:00:00+00:00")
    visit("uold", 5, "2026-06-20T00:00:00+00:00")


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_north_star_migration_upgrade_views_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    roundtrip_db = f"north_star_{uuid.uuid4().hex[:8]}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint.cursor().execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()
    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    from api.db_models import Base

    try:
        from sqlalchemy import create_engine

        engine = create_engine(roundtrip_url)
        users = Base.metadata.tables["users"]
        visits = Base.metadata.tables["user_visits"]
        # The ORM already declares the two columns this migration adds; strip
        # them for the pre-migration shape and restore in `finally` (the
        # metadata is shared process-wide).
        is_internal = users.c["is_internal"]
        session_id = visits.c["session_id"]
        try:
            users._columns.remove(is_internal)
            visits._columns.remove(session_id)
            Base.metadata.create_all(engine, tables=[users, visits])
        finally:
            if "is_internal" not in users.c:
                users.append_column(is_internal)
            if "session_id" not in visits.c:
                visits.append_column(session_id)
        engine.dispose()

        seed = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        try:
            _seed(seed)
        finally:
            seed.close()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _PRIOR_HEAD)
        command.upgrade(cfg, _NORTH_STAR_REV)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            cur = conn.cursor()

            col = _column(conn, "users", "is_internal")
            assert col["data_type"] == "boolean" and col["is_nullable"] == "NO"
            assert "false" in (col["column_default"] or "")
            col = _column(conn, "user_visits", "session_id")
            assert col["data_type"] == "text" and col["is_nullable"] == "YES"
            assert _column(conn, "job_apply_clicks", "job_age_seconds") is not None

            # Only the owner's account is flagged; nonadmin@nonadmin.com is not.
            cur.execute("SELECT id FROM users WHERE is_internal ORDER BY id")
            assert [r["id"] for r in cur.fetchall()] == ["uint"]

            cur.execute("SELECT * FROM metrics.signup_retention ORDER BY user_id")
            rows = {r["user_id"]: r for r in cur.fetchall()}
            assert set(rows) == {"ua", "ub", "uc"}
            assert {r["cohort_week"].isoformat() for r in rows.values()} == {"2026-07-06"}
            assert (rows["ua"]["back_day3plus"], rows["ua"]["back_day7plus"]) == (True, True)
            assert (rows["ub"]["back_day3plus"], rows["ub"]["back_day7plus"]) == (False, False)
            assert (rows["uc"]["back_day3plus"], rows["uc"]["back_day7plus"]) == (False, False)
            assert [rows[u]["weeks_returned"] for u in ("ua", "ub", "uc")] == [2, 0, 1]
            assert [rows[u]["came_back_after_14d"] for u in ("ua", "ub", "uc")] == [
                False, False, True,
            ]
            # All three have since gone 14+ days without a visit.
            assert all(r["had_14d_gap"] for r in rows.values())

            cur.execute("SELECT * FROM metrics.north_star_weekly")
            (week,) = cur.fetchall()
            assert week["cohort_week"].isoformat() == "2026-07-06"
            assert week["signups"] == 3
            assert week["mature"] is True
            assert week["weeks_returned_mature"] is True
            assert week["back_day3plus"] == Decimal("0.3333")
            assert week["back_day7plus"] == Decimal("0.3333")
            assert week["avg_weeks_returned"] == Decimal("1.0000")
            assert week["came_back_after_14d"] == Decimal("0.3333")

            # Apply clicks + sessions start after the migration ships.
            cur.execute(
                "UPDATE user_visits SET session_id = 's0' WHERE user_id = 'ua'"
                " AND visited_at = %s::timestamptz + interval '4 days'", (_SIGNUP,)
            )
            cur.execute(
                "UPDATE user_visits SET session_id = 's1' WHERE user_id = 'ua'"
                " AND visited_at = %s::timestamptz + interval '8 days'", (_SIGNUP,)
            )
            cur.execute("UPDATE user_visits SET session_id = 'sx' WHERE user_id = 'uint'")
            # 's1' is also on a visit; 's2' only on a click (PostHog rotated the
            # id after 30 idle minutes, no page load), so it adds a session.
            for uid, sid in (("ua", "s1"), ("ua", "s2"), ("uint", "sy")):
                cur.execute(
                    "INSERT INTO job_apply_clicks"
                    " (clicked_at, user_id, session_id, source_id, job_id, surface)"
                    " VALUES (%s::timestamptz + interval '8 days', %s, %s, 's', 'j', 'recent')",
                    (_SIGNUP, uid, sid),
                )
            cur.execute("SELECT * FROM metrics.apply_clicks_weekly ORDER BY week")
            weekly = [
                (r["week"].isoformat(), r["clicks"], r["sessions"], r["clicks_per_session"])
                for r in cur.fetchall()
            ]
            assert weekly == [
                ("2026-07-06", 0, 1, Decimal("0.0000")),
                ("2026-07-13", 2, 2, Decimal("1.0000")),
            ]

            # The read-only grant is guarded on the role existing: without it
            # the upgrade above still ran; with it the role can read the views.
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'claude_readonly'")
            if cur.fetchone() is not None:
                cur.execute(
                    "SELECT has_schema_privilege('claude_readonly', 'metrics', 'USAGE') AS s,"
                    " has_table_privilege('claude_readonly',"
                    " 'metrics.north_star_weekly', 'SELECT') AS v,"
                    " has_table_privilege('claude_readonly', 'job_apply_clicks', 'SELECT') AS t"
                )
                assert cur.fetchone() == {"s": True, "v": True, "t": True}
        finally:
            conn.close()

        command.downgrade(cfg, _PRIOR_HEAD)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'metrics'")
            assert cur.fetchone() is None
            assert _column(conn, "users", "is_internal") is None
            assert _column(conn, "user_visits", "session_id") is None
            cur.execute("SELECT to_regclass('public.job_apply_clicks') AS t")
            assert cur.fetchone()["t"] is None
            # The visit log itself survives.
            cur.execute("SELECT count(*) AS n FROM user_visits")
            assert cur.fetchone()["n"] == 9
        finally:
            conn.close()
    finally:
        maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
        maint.autocommit = True
        maint_cur = maint.cursor()
        maint_cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (roundtrip_db,),
        )
        maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
        maint.close()
