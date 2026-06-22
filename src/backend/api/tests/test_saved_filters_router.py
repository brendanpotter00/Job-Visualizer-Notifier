"""Integration tests for the saved-filters router.

The shared ``test_app`` fixture in conftest does not mount the saved-filters
router, so this module builds its own FastAPI app that mounts it at the real
prefix (``/api/users/saved-filters``) with the same auth + get_db overrides as
conftest. Covers all 7 endpoints: GET-never-404, 409 unknown active pointer,
409 duplicate name, 422 built-in-id mutation, 422 at list cap, 404 not-owned
PATCH/DELETE, and 401 for every route when unauthenticated.

Follows the test_users_router.py / test_features_router.py TestClient pattern.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth.dependencies import get_current_user
from api.dependencies import get_db
from api.routers import saved_filters
from api.services.saved_filters_service import (
    BUILTIN_SWE_LIST_ID,
    MAX_KEYWORD_LISTS_PER_USER,
)

from .conftest import TEST_DB_URL

_TEST_CLAIMS = {
    "sub": "auth0|test_user_123",
    "email": "test@example.com",
    "given_name": "Test",
    "family_name": "User",
    "picture": "https://example.com/photo.jpg",
}

PREFIX = "/api/users/saved-filters"


@pytest.fixture(scope="module")
def sf_app(db_conn):
    """FastAPI app mounting ONLY the saved-filters router (+ users for lazy row
    creation), wired to the test connection and a default authenticated user."""
    from api.routers import users
    from api.config import Settings

    app = FastAPI()
    app.include_router(users.router, prefix="/api/users")
    app.include_router(saved_filters.router, prefix=PREFIX)

    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _TEST_CLAIMS
    app.state.config = Settings(database_url=TEST_DB_URL)
    return app


@pytest.fixture(scope="module")
def sf_client(sf_app):
    return TestClient(sf_app)


def _create_user_row(sf_client):
    """GET /api/users lazily creates the caller's user row; return its id."""
    resp = sf_client.get("/api/users")
    assert resp.status_code == 200
    return resp.json()["id"]


# --- GET scalar saved filters -------------------------------------------------


class TestGetSavedFilters:
    def test_returns_defaults_when_no_user_row(self, sf_client):
        """Never 404s — a caller with no users row gets server defaults."""
        resp = sf_client.get(PREFIX)
        assert resp.status_code == 200
        body = resp.json()
        assert body["recentTimeWindow"] == "3h"
        assert body["trendTimeWindow"] == "7d"
        assert body["locations"] == []
        assert body["recentActiveKeywordListId"] is None

    def test_returns_defaults_after_user_created_no_row(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.get(PREFIX)
        assert resp.status_code == 200
        assert resp.json()["trendTimeWindow"] == "7d"


# --- PUT scalar saved filters -------------------------------------------------


class TestPutSavedFilters:
    def test_round_trip(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.put(
            PREFIX,
            json={
                "recentTimeWindow": "24h",
                "trendTimeWindow": "30d",
                "locations": ["San Francisco, CA, US"],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["recentTimeWindow"] == "24h"
        assert resp.json()["locations"] == ["San Francisco, CA, US"]

    def test_unknown_active_pointer_409(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.put(
            PREFIX,
            json={
                "recentTimeWindow": "3h",
                "trendTimeWindow": "7d",
                "locations": [],
                "trendActiveKeywordListId": "does-not-exist",
            },
        )
        assert resp.status_code == 409

    def test_builtin_pointer_accepted(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.put(
            PREFIX,
            json={
                "recentTimeWindow": "3h",
                "trendTimeWindow": "7d",
                "locations": [],
                "trendActiveKeywordListId": BUILTIN_SWE_LIST_ID,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["trendActiveKeywordListId"] == BUILTIN_SWE_LIST_ID

    def test_without_user_row_404(self, sf_client):
        # No GET /api/users first -> no user row -> PUT 404s.
        resp = sf_client.put(
            PREFIX,
            json={"recentTimeWindow": "3h", "trendTimeWindow": "7d", "locations": []},
        )
        assert resp.status_code == 404

    def test_rejects_bad_time_window_422(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.put(
            PREFIX,
            json={"recentTimeWindow": "not-a-window", "trendTimeWindow": "7d", "locations": []},
        )
        assert resp.status_code == 422


# --- Keyword lists ------------------------------------------------------------


class TestKeywordLists:
    def test_get_includes_builtin_for_new_user(self, sf_client):
        resp = sf_client.get(f"{PREFIX}/keyword-lists")
        assert resp.status_code == 200
        ids = [l["id"] for l in resp.json()["lists"]]
        assert ids == [BUILTIN_SWE_LIST_ID]

    def test_create_returns_201(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.post(
            f"{PREFIX}/keyword-lists",
            json={"name": "Backend", "tags": [{"text": "golang", "mode": "include"}]},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["name"] == "Backend"
        assert resp.json()["isBuiltin"] is False

    def test_create_duplicate_name_409(self, sf_client):
        _create_user_row(sf_client)
        sf_client.post(f"{PREFIX}/keyword-lists", json={"name": "Dup", "tags": []})
        resp = sf_client.post(
            f"{PREFIX}/keyword-lists", json={"name": "dup", "tags": []}
        )
        assert resp.status_code == 409

    def test_create_at_cap_422(self, sf_client):
        _create_user_row(sf_client)
        for i in range(MAX_KEYWORD_LISTS_PER_USER):
            r = sf_client.post(
                f"{PREFIX}/keyword-lists", json={"name": f"L{i}", "tags": []}
            )
            assert r.status_code == 201
        resp = sf_client.post(
            f"{PREFIX}/keyword-lists", json={"name": "over", "tags": []}
        )
        assert resp.status_code == 422

    def test_patch_builtin_422(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.patch(
            f"{PREFIX}/keyword-lists/{BUILTIN_SWE_LIST_ID}",
            json={"name": "Nope"},
        )
        assert resp.status_code == 422

    def test_patch_not_owned_404(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.patch(
            f"{PREFIX}/keyword-lists/no-such-id", json={"name": "X"}
        )
        assert resp.status_code == 404

    def test_patch_rename_collision_409(self, sf_client):
        _create_user_row(sf_client)
        sf_client.post(f"{PREFIX}/keyword-lists", json={"name": "One", "tags": []})
        two = sf_client.post(
            f"{PREFIX}/keyword-lists", json={"name": "Two", "tags": []}
        ).json()
        resp = sf_client.patch(
            f"{PREFIX}/keyword-lists/{two['id']}", json={"name": "one"}
        )
        assert resp.status_code == 409

    def test_patch_replaces_tags(self, sf_client):
        _create_user_row(sf_client)
        created = sf_client.post(
            f"{PREFIX}/keyword-lists", json={"name": "Mine", "tags": []}
        ).json()
        resp = sf_client.patch(
            f"{PREFIX}/keyword-lists/{created['id']}",
            json={"tags": [{"text": "new", "mode": "exclude"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == [{"text": "new", "mode": "exclude"}]

    def test_delete_builtin_422(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.delete(f"{PREFIX}/keyword-lists/{BUILTIN_SWE_LIST_ID}")
        assert resp.status_code == 422

    def test_delete_not_owned_404(self, sf_client):
        _create_user_row(sf_client)
        resp = sf_client.delete(f"{PREFIX}/keyword-lists/no-such-id")
        assert resp.status_code == 404

    def test_delete_returns_204_and_nulls_pointer(self, sf_client):
        _create_user_row(sf_client)
        created = sf_client.post(
            f"{PREFIX}/keyword-lists", json={"name": "Active", "tags": []}
        ).json()
        sf_client.put(
            PREFIX,
            json={
                "recentTimeWindow": "3h",
                "trendTimeWindow": "7d",
                "locations": [],
                "trendActiveKeywordListId": created["id"],
            },
        )
        resp = sf_client.delete(f"{PREFIX}/keyword-lists/{created['id']}")
        assert resp.status_code == 204
        prefs = sf_client.get(PREFIX).json()
        assert prefs["trendActiveKeywordListId"] is None


# --- Location search ----------------------------------------------------------


class TestLocationSearch:
    def test_requires_q(self, sf_client):
        resp = sf_client.get(f"{PREFIX}/locations/search")
        assert resp.status_code == 422

    def test_returns_matches(self, sf_client, db_conn):
        from psycopg2 import sql

        cur = db_conn.cursor()
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (canonical_name, kind) VALUES (%s, %s)"
            ).format(sql.Identifier("locations")),
            ("San Francisco, CA, US", "city"),
        )
        db_conn.commit()
        resp = sf_client.get(f"{PREFIX}/locations/search", params={"q": "San Fran"})
        assert resp.status_code == 200
        names = [r["canonicalName"] for r in resp.json()]
        assert "San Francisco, CA, US" in names


# --- Auth gate: every route rejects unauthenticated requests with 401 ---------


class TestAuthRequired:
    @pytest.fixture
    def no_auth_client(self, sf_app):
        saved = sf_app.dependency_overrides.pop(get_current_user, None)
        try:
            yield TestClient(sf_app)
        finally:
            if saved is not None:
                sf_app.dependency_overrides[get_current_user] = saved

    def test_get_saved_filters_401(self, no_auth_client):
        assert no_auth_client.get(PREFIX).status_code == 401

    def test_put_saved_filters_401(self, no_auth_client):
        resp = no_auth_client.put(
            PREFIX,
            json={"recentTimeWindow": "3h", "trendTimeWindow": "7d", "locations": []},
        )
        assert resp.status_code == 401

    def test_get_keyword_lists_401(self, no_auth_client):
        assert no_auth_client.get(f"{PREFIX}/keyword-lists").status_code == 401

    def test_post_keyword_list_401(self, no_auth_client):
        resp = no_auth_client.post(
            f"{PREFIX}/keyword-lists", json={"name": "X", "tags": []}
        )
        assert resp.status_code == 401

    def test_patch_keyword_list_401(self, no_auth_client):
        resp = no_auth_client.patch(
            f"{PREFIX}/keyword-lists/some-id", json={"name": "X"}
        )
        assert resp.status_code == 401

    def test_delete_keyword_list_401(self, no_auth_client):
        resp = no_auth_client.delete(f"{PREFIX}/keyword-lists/some-id")
        assert resp.status_code == 401

    def test_location_search_401(self, no_auth_client):
        resp = no_auth_client.get(f"{PREFIX}/locations/search", params={"q": "x"})
        assert resp.status_code == 401
