"""Integration tests for the public locations router (GET /api/locations/search).

Mounts ONLY the locations router — crucially WITHOUT any auth override — to
prove the endpoint is reachable by signed-out callers (the Recent/Trend filter
dropdowns it feeds are public). Also asserts the structured city/region/country/
remoteScope fields ride along so the frontend can cache a full descriptor.

Follows the TestClient pattern in test_saved_filters_router.py.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.dependencies import get_db
from api.routers import locations

PREFIX = "/api/locations"


@pytest.fixture(scope="module")
def loc_app(db_conn):
    """FastAPI app mounting ONLY the public locations router, wired to the test
    connection. No auth dependency override — the endpoint must not require one."""
    app = FastAPI()
    app.include_router(locations.router, prefix=PREFIX)

    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture(scope="module")
def loc_client(loc_app):
    return TestClient(loc_app)


def _insert_location(db_conn, **cols):
    """Insert one canonical locations row from keyword columns."""
    keys = list(cols)
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier("locations"),
        sql.SQL(", ").join(sql.Identifier(k) for k in keys),
        sql.SQL(", ").join(sql.Placeholder() for _ in keys),
    )
    cur = db_conn.cursor()
    cur.execute(stmt, [cols[k] for k in keys])
    db_conn.commit()


class TestPublicLocationSearch:
    def test_requires_q(self, loc_client):
        # Missing the required q param is a 422 even without auth.
        resp = loc_client.get(f"{PREFIX}/search")
        assert resp.status_code == 422

    def test_no_auth_required(self, loc_client, db_conn):
        # The whole point of the move: a signed-out caller gets 200, not 401.
        _insert_location(
            db_conn, canonical_name="Austin, TX, US", kind="city", city="Austin",
            region="TX", country="US",
        )
        resp = loc_client.get(f"{PREFIX}/search", params={"q": "Austin"})
        assert resp.status_code == 200

    def test_returns_structured_fields(self, loc_client, db_conn):
        # A non-US country row: the structured country code must come back so the
        # frontend can resolve "Japan" -> country=JP even for city-only jobs.
        _insert_location(db_conn, canonical_name="Japan", kind="country", country="JP")
        resp = loc_client.get(f"{PREFIX}/search", params={"q": "Japan"})
        assert resp.status_code == 200
        rows = {r["canonicalName"]: r for r in resp.json()}
        assert "Japan" in rows
        japan = rows["Japan"]
        assert japan["kind"] == "country"
        assert japan["country"] == "JP"
        # camelCase alias for remote_scope is present (None here).
        assert "remoteScope" in japan
        assert japan["city"] is None and japan["region"] is None

    def test_open_only_filters_to_locations_with_open_jobs(self, loc_client, db_conn):
        # A location with no jobs is excluded when openOnly=true but included by
        # default (the dropdown wants ALL locations).
        _insert_location(
            db_conn, canonical_name="Nowheresville, ZZ, US", kind="city",
            city="Nowheresville", region="ZZ", country="US",
        )
        default_names = [
            r["canonicalName"]
            for r in loc_client.get(
                f"{PREFIX}/search", params={"q": "Nowheresville"}
            ).json()
        ]
        assert "Nowheresville, ZZ, US" in default_names

        open_only_names = [
            r["canonicalName"]
            for r in loc_client.get(
                f"{PREFIX}/search",
                params={"q": "Nowheresville", "openOnly": "true"},
            ).json()
        ]
        assert "Nowheresville, ZZ, US" not in open_only_names
