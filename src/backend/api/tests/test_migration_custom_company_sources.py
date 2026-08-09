"""Schema-contract tests for the E7 Phase 1 migration (fb8467065dfc).

The parity + single-head tests prove the migration equals the ORM models and
keeps one head; these lock the concrete columns/tables/defaults the feature
depends on so an accidental model removal fails loudly here.
"""

from __future__ import annotations

from psycopg2 import sql


def _columns(db_conn, table: str) -> dict[str, dict]:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT column_name, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    )
    return {r["column_name"]: r for r in cur.fetchall()}


def test_companies_has_visibility_columns(db_conn):
    cols = _columns(db_conn, "companies")
    for name in (
        "visibility", "cadence_hours", "next_run_at", "tracking_started_at",
        "health_state", "last_success_at", "consecutive_failures",
    ):
        assert name in cols, f"companies.{name} missing"
    assert cols["visibility"]["is_nullable"] == "NO"
    assert "public" in (cols["visibility"]["column_default"] or "")
    assert cols["consecutive_failures"]["is_nullable"] == "NO"


def test_scrape_runs_has_source_id_and_success(db_conn):
    cols = _columns(db_conn, "scrape_runs")
    assert "source_id" in cols
    assert "success" in cols
    # Both nullable, no server default (catalog-only add on a large table).
    assert cols["source_id"]["is_nullable"] == "YES"
    assert cols["success"]["is_nullable"] == "YES"


def test_new_tables_exist(db_conn):
    cur = db_conn.cursor()
    for table in (
        "user_companies", "company_scripts", "company_harvests",
        "company_add_attempts",
    ):
        cur.execute("SELECT to_regclass(%s) AS t", (table,))
        assert cur.fetchone()["t"] is not None, f"{table} missing"


def test_visibility_partial_index_exists(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "SELECT indexdef FROM pg_indexes "
        "WHERE schemaname = current_schema() AND indexname = 'ix_companies_visibility'"
    )
    row = cur.fetchone()
    assert row is not None
    # Partial predicate on the non-public subset.
    assert "public" in row["indexdef"]


def test_company_insert_defaults_visibility_public(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token) "
            "VALUES ('plain-co', 'Plain', 'greenhouse', 'plain')"
        ).format(sql.Identifier("companies"))
    )
    db_conn.commit()
    cur.execute("SELECT visibility, consecutive_failures FROM companies WHERE id = 'plain-co'")
    row = cur.fetchone()
    assert row["visibility"] == "public"
    assert row["consecutive_failures"] == 0
