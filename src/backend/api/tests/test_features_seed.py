"""Tests for idempotent starter-features seed + completion reconcile."""

from psycopg2 import sql

from api.services.features_seed import (
    COMPLETED_FEATURE_IDS,
    STARTER_FEATURES,
    reconcile_completed_features,
    seed_starter_features,
)

_FEATURES = sql.Identifier("features")


def _insert_feature(db_conn, feature_id: str) -> None:
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("INSERT INTO {} (id, title, description) VALUES (%s, %s, %s)").format(
            _FEATURES
        ),
        (feature_id, feature_id, "desc"),
    )
    db_conn.commit()


def _completed_at_by_id(db_conn) -> dict:
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("SELECT id, completed_at FROM {} ORDER BY id").format(_FEATURES)
    )
    return {r["id"]: r["completed_at"] for r in cursor.fetchall()}


def test_seeds_all_starter_features(db_conn):
    inserted = seed_starter_features(db_conn)
    assert inserted == len(STARTER_FEATURES)
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("SELECT id, title, description FROM {} ORDER BY id").format(_FEATURES)
    )
    rows = cursor.fetchall()
    seeded = {(r["id"], r["title"], r["description"]) for r in rows}
    assert seeded == set(STARTER_FEATURES)


def test_seed_is_idempotent(db_conn):
    seed_starter_features(db_conn)
    second = seed_starter_features(db_conn)
    assert second == 0
    cursor = db_conn.cursor()
    cursor.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(_FEATURES))
    assert cursor.fetchone()["n"] == len(STARTER_FEATURES)


def test_seed_preserves_existing_rows(db_conn):
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("INSERT INTO {} (id, title, description) VALUES (%s, %s, %s)").format(
            _FEATURES
        ),
        ("resume-match-ai", "Custom Title", "Custom Desc"),
    )
    db_conn.commit()
    seed_starter_features(db_conn)
    cursor.execute(
        sql.SQL("SELECT title, description FROM {} WHERE id = %s").format(_FEATURES),
        ("resume-match-ai",),
    )
    row = cursor.fetchone()
    assert row["title"] == "Custom Title"
    assert row["description"] == "Custom Desc"


def test_seed_ids_match_plan_md():
    ids = [f[0] for f in STARTER_FEATURES]
    assert ids == [
        "resume-match-ai",
        "location-normalization",
        "mcp-server",
        "custom-dashboards",
    ]


def test_completed_ids_are_known_features():
    # Every id we mark completed must be a real seeded feature, else the
    # reconcile silently matches nothing.
    starter_ids = {f[0] for f in STARTER_FEATURES}
    assert set(COMPLETED_FEATURE_IDS) <= starter_ids


def test_seed_marks_shipped_features_completed(db_conn):
    # seed_starter_features runs the reconcile at the end, so location
    # normalization comes out completed and the rest stay open.
    seed_starter_features(db_conn)
    by_id = _completed_at_by_id(db_conn)
    assert by_id["location-normalization"] is not None
    assert by_id["resume-match-ai"] is None
    assert by_id["mcp-server"] is None
    assert by_id["custom-dashboards"] is None


def test_reconcile_marks_only_completed_ids(db_conn):
    _insert_feature(db_conn, "location-normalization")
    _insert_feature(db_conn, "mcp-server")
    marked = reconcile_completed_features(db_conn)
    assert marked == 1
    by_id = _completed_at_by_id(db_conn)
    assert by_id["location-normalization"] is not None
    assert by_id["mcp-server"] is None


def test_reconcile_is_idempotent_and_does_not_restamp(db_conn):
    _insert_feature(db_conn, "location-normalization")
    first = reconcile_completed_features(db_conn)
    assert first == 1
    by_id = _completed_at_by_id(db_conn)
    ts_first = by_id["location-normalization"]

    second = reconcile_completed_features(db_conn)
    assert second == 0
    by_id = _completed_at_by_id(db_conn)
    # The completed_at IS NULL guard means the ship date is never moved.
    assert by_id["location-normalization"] == ts_first


def test_reconcile_with_no_matching_rows_is_noop(db_conn):
    marked = reconcile_completed_features(db_conn)
    assert marked == 0
