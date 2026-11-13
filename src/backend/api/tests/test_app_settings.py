"""ADM-2: the admin settings API and its no-seed-row default path.

The interesting cases here are all about ABSENCE. `app_settings` ships with no
seed row on purpose — absent means the code default — so "there is no row" is the
DEFAULT path through every function in this file, not an edge case. If it were
handled anywhere as an error, a fresh database and a rolled-back migration would
both break the admin page.
"""

from __future__ import annotations

import pytest

@pytest.fixture(autouse=True)
def _clean_settings(db_conn):
    cur = db_conn.cursor()
    cur.execute("TRUNCATE app_settings")
    db_conn.commit()
    yield
    cur.execute("TRUNCATE app_settings")
    db_conn.commit()


class TestAdminSettings:
    def test_get_on_an_empty_table_materializes_the_default(self, client, db_conn):
        """THE DEFAULT PATH. No seed row exists, and the response is still a
        complete list — so the UI never handles "missing"."""
        resp = client.get("/api/admin/settings")
        assert resp.status_code == 200, resp.text
        rows = resp.json()["settings"]
        assert len(rows) == 1
        row = rows[0]
        assert row["key"] == "swe_subcategories_enabled"
        assert row["value"] is False
        assert row["updatedAt"] is None
        assert row["updatedBy"] is None

    def test_value_is_a_real_bool_not_a_one(self, client, db_conn):
        client.put(
            "/api/admin/settings/swe_subcategories_enabled", json={"value": True}
        )
        row = client.get("/api/admin/settings").json()["settings"][0]
        assert row["value"] is True
        assert not isinstance(row["value"], int) or isinstance(row["value"], bool)

    def test_put_then_get_round_trips(self, client, db_conn):
        put = client.put(
            "/api/admin/settings/swe_subcategories_enabled", json={"value": True}
        )
        assert put.status_code == 200, put.text
        assert put.json()["value"] is True
        assert put.json()["updatedBy"] == "test@example.com"
        assert put.json()["updatedAt"] is not None

        row = client.get("/api/admin/settings").json()["settings"][0]
        assert row["value"] is True

        # And back off again.
        client.put(
            "/api/admin/settings/swe_subcategories_enabled", json={"value": False}
        )
        assert client.get("/api/admin/settings").json()["settings"][0]["value"] is False

    def test_un_allowlisted_key_404s(self, client, db_conn):
        resp = client.put("/api/admin/settings/not_a_real_setting", json={"value": True})
        assert resp.status_code == 404
        # And nothing was written.
        cur = db_conn.cursor()
        cur.execute("SELECT count(*) AS n FROM app_settings")
        assert cur.fetchone()["n"] == 0

    def test_uncoercible_value_400s(self, client, db_conn):
        resp = client.put(
            "/api/admin/settings/swe_subcategories_enabled", json={"value": "maybe"}
        )
        assert resp.status_code == 400

    def test_unknown_body_key_422s(self, client, db_conn):
        resp = client.put(
            "/api/admin/settings/swe_subcategories_enabled",
            json={"value": True, "reason": "because"},
        )
        assert resp.status_code == 422

    def test_a_pre_migration_table_reads_as_the_default_not_a_500(
        self, client, db_conn
    ):
        """The regclass guard. With no seed row there is nothing to prove the
        table exists, so a process running ahead of the migration must fall back
        to defaults rather than raise."""
        cur = db_conn.cursor()
        cur.execute("DROP TABLE IF EXISTS app_settings")
        db_conn.commit()
        try:
            resp = client.get("/api/admin/settings")
            assert resp.status_code == 200, resp.text
            assert resp.json()["settings"][0]["value"] is False
        finally:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS app_settings ("
                "  key TEXT PRIMARY KEY,"
                "  value JSONB NOT NULL,"
                "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                "  updated_by TEXT)"
            )
            db_conn.commit()

    def test_a_garbage_stored_value_degrades_to_the_default(self, client, db_conn):
        """A hand-edited row must not break the admin page."""
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO app_settings (key, value) VALUES "
            "('swe_subcategories_enabled', '\"banana\"'::jsonb)"
        )
        db_conn.commit()
        row = client.get("/api/admin/settings").json()["settings"][0]
        assert row["value"] is False
