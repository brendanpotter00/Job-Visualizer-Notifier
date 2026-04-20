"""Tests for idempotent starter-features seed."""

from psycopg2 import sql

from api.services.features_seed import STARTER_FEATURES, seed_starter_features


def test_seeds_all_starter_features(db_conn, test_env):
    inserted = seed_starter_features(db_conn, test_env)
    assert inserted == len(STARTER_FEATURES)
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("SELECT id, title, description FROM {} ORDER BY id").format(
            sql.Identifier(f"features_{test_env}")
        )
    )
    rows = cursor.fetchall()
    seeded = {(r["id"], r["title"], r["description"]) for r in rows}
    assert seeded == set(STARTER_FEATURES)


def test_seed_is_idempotent(db_conn, test_env):
    seed_starter_features(db_conn, test_env)
    second = seed_starter_features(db_conn, test_env)
    assert second == 0
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
            sql.Identifier(f"features_{test_env}")
        )
    )
    assert cursor.fetchone()["n"] == len(STARTER_FEATURES)


def test_seed_preserves_existing_rows(db_conn, test_env):
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("INSERT INTO {} (id, title, description) VALUES (%s, %s, %s)").format(
            sql.Identifier(f"features_{test_env}")
        ),
        ("resume-match-ai", "Custom Title", "Custom Desc"),
    )
    db_conn.commit()
    seed_starter_features(db_conn, test_env)
    cursor.execute(
        sql.SQL("SELECT title, description FROM {} WHERE id = %s").format(
            sql.Identifier(f"features_{test_env}")
        ),
        ("resume-match-ai",),
    )
    row = cursor.fetchone()
    assert row["title"] == "Custom Title"
    assert row["description"] == "Custom Desc"


def test_seed_ids_match_plan_md():
    ids = [f[0] for f in STARTER_FEATURES]
    assert ids == ["resume-match-ai", "location-normalization", "mcp-server"]
