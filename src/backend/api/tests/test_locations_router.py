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


def _insert_location(db_conn, **cols) -> int:
    """Insert one canonical locations row from keyword columns; return its id."""
    keys = list(cols)
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
        sql.Identifier("locations"),
        sql.SQL(", ").join(sql.Identifier(k) for k in keys),
        sql.SQL(", ").join(sql.Placeholder() for _ in keys),
    )
    cur = db_conn.cursor()
    cur.execute(stmt, [cols[k] for k in keys])
    location_id = cur.fetchone()["id"]
    db_conn.commit()
    return int(location_id)


def _link_open_job(db_conn, location_id, status="OPEN"):
    """Seed one job_listings row (default status OPEN) and a job_locations row
    linking it to ``location_id`` — so the open_only EXISTS join can find it."""
    import uuid

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at,"
            " first_seen_at, last_seen_at, status) VALUES"
            " (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("job_listings")),
        (
            job_id,
            "Software Engineer",
            "google",
            "https://careers.example.com/1",
            "test_scraper",
            "2025-01-10T10:00:00Z",
            "2025-01-10T10:00:00Z",
            "2025-01-15T10:00:00Z",
            status,
        ),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (job_listing_id, normalized_location_id, is_primary)"
            " VALUES (%s, %s, %s)"
        ).format(sql.Identifier("job_locations")),
        (job_id, location_id, True),
    )
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

    def test_prefix_match_ranks_before_midstring(self, loc_client, db_conn):
        # Pins the ORDER BY contract:
        #   (canonical_name ILIKE 'q%') DESC, length(canonical_name) ASC, name ASC
        # i.e. prefix matches first, then shorter names, then alphabetical.
        # Uses a "Zephyria" token no other test seeds (locations aren't
        # truncated between tests in this module).
        _insert_location(
            db_conn, canonical_name="New Zephyria, NY, US", kind="city",
            city="New Zephyria", region="NY", country="US",
        )
        _insert_location(
            db_conn, canonical_name="Zephyria Heights, CA, US", kind="city",
            city="Zephyria Heights", region="CA", country="US",
        )
        _insert_location(
            db_conn, canonical_name="Zephyria, CA, US", kind="city",
            city="Zephyria", region="CA", country="US",
        )
        names = [
            r["canonicalName"]
            for r in loc_client.get(
                f"{PREFIX}/search", params={"q": "Zephyria"}
            ).json()
        ]
        # Prefix + shortest canonical_name ranks first.
        assert names[0] == "Zephyria, CA, US"
        # Shorter prefix match precedes the longer prefix match...
        assert names.index("Zephyria, CA, US") < names.index("Zephyria Heights, CA, US")
        # ...and both prefix matches precede the mid-string ("New Zephyria") match.
        assert names.index("Zephyria Heights, CA, US") < names.index("New Zephyria, NY, US")

    def test_limit_zero_is_rejected(self, loc_client):
        # limit has a hard floor of 1 (the only in-code result-size guardrail).
        resp = loc_client.get(f"{PREFIX}/search", params={"q": "a", "limit": 0})
        assert resp.status_code == 422

    def test_limit_above_max_is_rejected(self, loc_client):
        # limit has a hard ceiling of 50 — 51 must be rejected before any query.
        resp = loc_client.get(f"{PREFIX}/search", params={"q": "a", "limit": 51})
        assert resp.status_code == 422

    def test_limit_caps_returned_rows(self, loc_client, db_conn):
        # A small limit actually caps the number of returned rows.
        for i in range(4):
            _insert_location(
                db_conn, canonical_name=f"Caphold {i}, XX, US", kind="city",
                city=f"Caphold {i}", region="XX", country="US",
            )
        resp = loc_client.get(
            f"{PREFIX}/search", params={"q": "Caphold", "limit": 2}
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_open_only_includes_location_with_open_job(self, loc_client, db_conn):
        # Positive open_only case: a location WITH an OPEN job is RETURNED. A
        # broken EXISTS join (always-false) would silently pass the excludes-only
        # test above, so this pins the join actually matches.
        loc_id = _insert_location(
            db_conn, canonical_name="Openton, WA, US", kind="city",
            city="Openton", region="WA", country="US",
        )
        _link_open_job(db_conn, loc_id)
        names = [
            r["canonicalName"]
            for r in loc_client.get(
                f"{PREFIX}/search",
                params={"q": "Openton", "openOnly": "true"},
            ).json()
        ]
        assert "Openton, WA, US" in names

    def test_open_only_excludes_location_with_only_closed_job(self, loc_client, db_conn):
        # The EXISTS join is gated on j.status = 'OPEN': a location whose only
        # job is CLOSED is excluded under openOnly but present by default.
        loc_id = _insert_location(
            db_conn, canonical_name="Closedton, OR, US", kind="city",
            city="Closedton", region="OR", country="US",
        )
        _link_open_job(db_conn, loc_id, status="CLOSED")
        open_only_names = [
            r["canonicalName"]
            for r in loc_client.get(
                f"{PREFIX}/search",
                params={"q": "Closedton", "openOnly": "true"},
            ).json()
        ]
        assert "Closedton, OR, US" not in open_only_names
        default_names = [
            r["canonicalName"]
            for r in loc_client.get(
                f"{PREFIX}/search", params={"q": "Closedton"}
            ).json()
        ]
        assert "Closedton, OR, US" in default_names
