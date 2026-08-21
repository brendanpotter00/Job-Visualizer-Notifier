"""Integration tests for the ``/api/users/companies`` endpoints (E7 Phase 1).

Discovery of a direct ``boards.greenhouse.io/<token>`` URL is IO-free (L0), so
the only outbound call is the probe (``greenhouse_client.fetch_jobs``), mocked
here with an ``httpx.MockTransport`` injected via the router's ``_http_client``
factory. The non-ATS case exercises the full discovery ladder and mocks DNS +
transport the same way ``test_companies_resolve_endpoint`` does.
"""

from __future__ import annotations

import socket

import httpx
import psycopg2
import pytest
from psycopg2 import sql

import api.services.discovery.progress as dp
from api.auth.dependencies import get_current_user
from api.config import settings
from api.services import custom_companies_service as svc
from api.services.user_service import get_or_create_user
from scripts.shared.constants import custom

GREENHOUSE_URL = "https://boards.greenhouse.io/duolingo"


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)


@pytest.fixture(autouse=True)
def restore_auth(client):
    """Each test may re-point get_current_user; restore the default afterward."""
    original = client.app.dependency_overrides.get(get_current_user)
    yield
    if original is not None:
        client.app.dependency_overrides[get_current_user] = original


def _login(client, sub: str, email: str) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: {
        "sub": sub, "email": email,
        "given_name": "A", "family_name": "B", "picture": None,
    }


def _raw_job(i: int) -> dict:
    return {
        "id": i, "title": "Engineer", "absolute_url": f"https://x/{i}",
        "location": {"name": "Remote"}, "offices": [{"name": "Remote"}],
        "departments": [{"name": "Eng"}], "metadata": [],
        "first_published": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z", "content": "<p>d</p>",
    }


def _install_greenhouse(monkeypatch, job_ids: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        if "boards-api.greenhouse.io/v1/boards/duolingo/jobs" in str(request.url):
            return httpx.Response(200, json={"jobs": [_raw_job(i) for i in job_ids]})
        return httpx.Response(404)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.user_companies._http_client", factory)


def _user_id(db_conn, email: str) -> str:
    """The users row the logged-in caller resolves to (created on demand), so a test can
    seed service rows the endpoint will then read back for that same caller."""
    row = get_or_create_user(
        db_conn, auth0_id=f"auth0|{email}", email=email,
        given_name="A", family_name="B", picture_url=None,
    )
    return str(row["id"])


def _count(db_conn, table: str, where: str = "", params: tuple = ()) -> int:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT count(*) AS n FROM {} " + where).format(sql.Identifier(table)),
        params,
    )
    return int(cur.fetchone()["n"])


def _seed_job_for(
    db_conn, company_id: str, job_id: str, *, first_seen_at: str = "2025-01-01T00:00:00Z",
    status: str = "OPEN",
) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("job_listings")),
        (job_id, "Eng", company_id, "https://x/1", custom(company_id),
         "2025-01-01T00:00:00Z", first_seen_at, status),
    )
    db_conn.commit()


def _seed_public_job(db_conn, job_id: str, company: str = "pub-co") -> None:
    """A PUBLIC listing, so a purge can be shown not to reach across the boundary."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES (%s, %s, 'greenhouse', %s, TRUE, 'public') ON CONFLICT DO NOTHING"
        ).format(sql.Identifier("companies")),
        (company, company, company),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, 'Eng', %s, 'https://x/p', "
            "'greenhouse_api', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', 'OPEN')"
        ).format(sql.Identifier("job_listings")),
        (job_id, company),
    )
    db_conn.commit()


def _seed_location(db_conn, name: str) -> int:
    # ``remote_scope`` is part of ``uq_locations_canonical`` (NULLS NOT DISTINCT),
    # so it carries the uniqueness here — the ``db_conn`` fixture is module-scoped
    # and two bare kind='remote' rows would collide across tests.
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (canonical_name, kind, remote_scope) "
            "VALUES (%s, 'remote', %s) RETURNING id"
        ).format(sql.Identifier("locations")),
        (name, name),
    )
    db_conn.commit()
    return int(cur.fetchone()["id"])


def _link_location(db_conn, job_id: str, location_id: int) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (job_listing_id, normalized_location_id, is_primary) "
            "VALUES (%s, %s, TRUE)"
        ).format(sql.Identifier("job_locations")),
        (job_id, location_id),
    )
    db_conn.commit()


class _FailingCursor:
    """Delegates to a real cursor but raises on the first statement containing
    ``needle`` — used to prove the purge is one transaction."""

    def __init__(self, cursor, needle: str) -> None:
        self._cursor = cursor
        self._needle = needle

    def execute(self, query, params=None):
        if self._needle in str(query):
            raise psycopg2.OperationalError("injected failure")
        return self._cursor.execute(query, params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _FailingConn:
    def __init__(self, conn, needle: str) -> None:
        self._conn = conn
        self._needle = needle

    def cursor(self, *args, **kwargs):
        return _FailingCursor(self._conn.cursor(*args, **kwargs), self._needle)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _seed_sibling_rows(db_conn, company_id: str) -> None:
    """One row in each per-company sidecar the purge is responsible for: a
    location link per job, a tag, an enrichment row, a harvest and a scrape run."""
    source_id = custom(company_id)
    loc_id = _seed_location(db_conn, f"Remote {company_id}")
    for job_id in ("j1", "j2"):
        _link_location(db_conn, job_id, loc_id)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (source_id, job_listing_id, tag) VALUES (%s, 'j1', 'go')"
        ).format(sql.Identifier("job_tags")),
        (source_id,),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (source_id, job_listing_id) VALUES (%s, 'j1')"
        ).format(sql.Identifier("job_enrichment")),
        (source_id,),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (company_id, run_id, started_at, verdict, oracle_kind) "
            "VALUES (%s, 'run-1', now(), 'UNVERIFIED', 'none')"
        ).format(sql.Identifier("company_harvests")),
        (company_id,),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (run_id, company, started_at, mode, source_id) "
            "VALUES ('run-1', %s, '2025-01-01T00:00:00Z', 'full', %s)"
        ).format(sql.Identifier("scrape_runs")),
        (company_id, source_id),
    )
    db_conn.commit()


# --- POST ---------------------------------------------------------------------


def test_add_creates_all_four_rows(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ats"] == "greenhouse"
    assert body["boardToken"] == "duolingo"
    assert body["healthState"] == "unverified"
    assert body["sourceId"] == custom(body["id"])
    assert body["openJobCount"] == 0
    company_id = body["id"]

    assert _count(db_conn, "companies", "WHERE id = %s AND visibility = 'user' AND enabled", (company_id,)) == 1
    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (company_id,)) == 1
    assert _count(db_conn, "company_scripts", "WHERE company_id = %s", (company_id,)) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE company_id = %s AND outcome = 'added'", (company_id,)) == 1

    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT script, transport, oracle_kind, script_version FROM {} WHERE company_id = %s")
        .format(sql.Identifier("company_scripts")),
        (company_id,),
    )
    row = cur.fetchone()
    assert row["script"] == {"kind": "ats_client", "provider": "greenhouse", "token": "duolingo"}
    assert row["transport"] == "ats_client"
    # E7 Phase 2 (DECISION D2): a new add stores the real provider-derived oracle
    # — Greenhouse is declared_probed (its meta.total is the trusted total).
    assert row["oracle_kind"] == "declared_probed"
    assert row["script_version"] == 1


def test_add_is_idempotent_per_user(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])

    first = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert first.status_code == 201
    second = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    # Exactly one of each core row; the audit log records both attempts.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "user_companies") == 1
    assert _count(db_conn, "company_scripts") == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'added'") == 2


def test_two_users_get_distinct_companies_and_delete_is_isolated(client, db_conn, monkeypatch):
    _install_greenhouse(monkeypatch, [1, 2, 3])

    _login(client, "auth0|A", "a@example.com")
    a = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()

    _login(client, "auth0|B", "b@example.com")
    b = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()

    assert a["id"] != b["id"]
    assert a["sourceId"] != b["sourceId"]
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 2

    # Each user's board carries its own jobs under its own custom:<id> namespace.
    _seed_job_for(db_conn, a["id"], "ja")
    _seed_job_for(db_conn, b["id"], "jb")

    # A removes A's company (last owner → purged). B's rows untouched. This is
    # the assertion that proves the hard delete cannot cross users: the two rows
    # were minted by the SAME board URL, so a delete keyed on anything but the
    # per-user company id would take B's data with it.
    _login(client, "auth0|A", "a@example.com")
    resp = client.delete(f"/api/users/companies/{a['id']}")
    assert resp.status_code == 204

    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (a["id"],)) == 0
    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (b["id"],)) == 1
    assert _count(db_conn, "companies", "WHERE id = %s", (a["id"],)) == 0
    assert _count(db_conn, "companies", "WHERE id = %s AND enabled", (b["id"],)) == 1
    assert _count(db_conn, "job_listings", "WHERE source_id = %s", (custom(a["id"]),)) == 0
    assert _count(db_conn, "job_listings", "WHERE source_id = %s", (custom(b["id"]),)) == 1
    assert _count(db_conn, "company_scripts", "WHERE company_id = %s", (b["id"],)) == 1


# --- GET list -----------------------------------------------------------------


def test_get_returns_owner_list(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    _seed_job_for(db_conn, added["id"], "900")

    resp = client.get("/api/users/companies")
    assert resp.status_code == 200
    companies = resp.json()["companies"]
    assert len(companies) == 1
    assert companies[0]["id"] == added["id"]
    assert companies[0]["healthState"] == "unverified"
    assert companies[0]["openJobCount"] == 1


# --- DELETE -------------------------------------------------------------------


def test_delete_last_owner_purges_the_company_and_everything_under_it(
    client, db_conn, monkeypatch
):
    """The owner's bug: Remove left an ownerless company, its recipe and 10,000
    job rows alive forever — invisible to every UI and unreachable by a re-add.
    Remove must take the whole per-company footprint with it."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    company_id = added["id"]
    source_id = custom(company_id)
    _seed_job_for(db_conn, company_id, "j1")
    _seed_job_for(db_conn, company_id, "j2")
    _seed_sibling_rows(db_conn, company_id)

    # Everything is there before the delete — otherwise the assertions below
    # would pass against a fixture that never wrote anything.
    assert _count(db_conn, "job_listings", "WHERE source_id = %s", (source_id,)) == 2
    assert _count(db_conn, "job_freshness", "WHERE source_id = %s", (source_id,)) == 2
    assert _count(db_conn, "job_locations", "WHERE job_listing_id IN ('j1','j2')") == 2
    assert _count(db_conn, "job_tags", "WHERE source_id = %s", (source_id,)) == 1
    assert _count(db_conn, "job_enrichment", "WHERE source_id = %s", (source_id,)) == 1
    assert _count(db_conn, "company_harvests", "WHERE company_id = %s", (company_id,)) == 1
    assert _count(db_conn, "scrape_runs", "WHERE company = %s", (company_id,)) == 1

    resp = client.delete(f"/api/users/companies/{company_id}")
    assert resp.status_code == 204

    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (company_id,)) == 0
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 0
    assert _count(db_conn, "company_scripts", "WHERE company_id = %s", (company_id,)) == 0
    assert _count(db_conn, "job_listings", "WHERE source_id = %s", (source_id,)) == 0
    # Cascaded by the composite FK, not by an explicit DELETE — assert it anyway,
    # because losing that FK would silently strand a freshness row per job.
    assert _count(db_conn, "job_freshness", "WHERE source_id = %s", (source_id,)) == 0
    assert _count(db_conn, "job_locations", "WHERE job_listing_id IN ('j1','j2')") == 0
    assert _count(db_conn, "job_tags", "WHERE source_id = %s", (source_id,)) == 0
    assert _count(db_conn, "job_enrichment", "WHERE source_id = %s", (source_id,)) == 0
    assert _count(db_conn, "company_harvests", "WHERE company_id = %s", (company_id,)) == 0
    assert _count(db_conn, "scrape_runs", "WHERE company = %s", (company_id,)) == 0

    # DELIBERATELY KEPT: the append-only add audit.
    assert _count(
        db_conn, "company_add_attempts", "WHERE company_id = %s", (company_id,)
    ) == 1


def test_remove_leaves_no_row_that_a_later_re_add_could_collide_with(
    client, db_conn, monkeypatch
):
    """Re-adding the same board after a Remove must behave like a first add: a
    fresh company id, a fresh namespace, zero carried-over jobs. Under the old
    soft-disable the ownership row was gone but the company row was not, so the
    board could never be reclaimed and its jobs were orphaned for good."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    first = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    _seed_job_for(db_conn, first["id"], "old-job")

    assert client.delete(f"/api/users/companies/{first['id']}").status_code == 204

    second = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["id"] != first["id"]
    assert body["openJobCount"] == 0
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "job_listings", "WHERE source_id = %s", (custom(first["id"]),)) == 0


def test_purge_keeps_location_links_of_a_colliding_public_job(client, db_conn, monkeypatch):
    """``job_locations`` carries no source_id, so a bare
    ``job_listing_id IN (...)`` delete would drop the location tags of an
    unrelated PUBLIC listing that happens to share a job id."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()

    shared_id = "collide-1"
    _seed_job_for(db_conn, added["id"], shared_id)
    _seed_public_job(db_conn, shared_id)
    loc_id = _seed_location(db_conn, "Remote")
    _link_location(db_conn, shared_id, loc_id)
    assert _count(db_conn, "job_locations", "WHERE job_listing_id = %s", (shared_id,)) == 1

    assert client.delete(f"/api/users/companies/{added['id']}").status_code == 204

    # The custom listing is gone; the public one — and its location link — is not.
    assert _count(
        db_conn, "job_listings", "WHERE source_id = %s", (custom(added["id"]),)
    ) == 0
    assert _count(db_conn, "job_listings", "WHERE source_id = 'greenhouse_api'") == 1
    assert _count(db_conn, "job_locations", "WHERE job_listing_id = %s", (shared_id,)) == 1


def test_purge_is_one_transaction(client, db_conn, monkeypatch):
    """A partial purge would strand exactly the rows this exists to remove, with
    no owner left to retry it. Break the LAST statement and assert the ownership
    row and the jobs deleted earlier in the same transaction both came back."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    company_id = added["id"]
    _seed_job_for(db_conn, company_id, "j1")

    user_id = _user_id(db_conn, "a@example.com")

    # A proxy rather than monkeypatching the connection: psycopg2's connection is
    # a C extension type whose ``cursor`` attribute cannot be reassigned.
    with pytest.raises(psycopg2.Error):
        svc.remove_owned_company(
            _FailingConn(db_conn, "DELETE FROM companies"), user_id, company_id
        )

    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (company_id,)) == 1
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1
    assert _count(db_conn, "company_scripts", "WHERE company_id = %s", (company_id,)) == 1
    assert _count(db_conn, "job_listings", "WHERE source_id = %s", (custom(company_id),)) == 1


def test_delete_unknown_company_is_404(client, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    # No user row / no ownership → 404.
    resp = client.delete("/api/users/companies/u-doesnotexist")
    assert resp.status_code == 404


def test_delete_an_id_we_could_never_have_minted_is_404_not_500(client, db_conn):
    """``company_id`` arrives straight off the URL path and ``custom()`` RAISES on
    a shape it would not have minted. Resolving the source_id before the ownership
    check turned every such request into an unhandled 500.

    The user row MUST exist first: without it the router 404s on
    ``get_user_by_email`` and never calls the service at all, which would make
    this test pass no matter what the service does."""
    _login(client, "auth0|M", "mint@example.com")
    _user_id(db_conn, "mint@example.com")
    assert client.delete("/api/users/companies/NOT_A_MINTED_ID").status_code == 404


# --- GET owner-scoped jobs ----------------------------------------------------


def test_get_jobs_403_for_non_owner_200_for_owner(client, db_conn, monkeypatch):
    _install_greenhouse(monkeypatch, [1, 2, 3])
    _login(client, "auth0|A", "a@example.com")
    a = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    _seed_job_for(db_conn, a["id"], "555")

    # Owner: 200 with the job.
    resp_owner = client.get(f"/api/users/companies/{a['id']}/jobs")
    assert resp_owner.status_code == 200
    ids = {j["id"] for j in resp_owner.json()}
    assert "555" in ids

    # Non-owner B: 403.
    _login(client, "auth0|B", "b@example.com")
    # Ensure B exists as a user but does not own A's company.
    client.get("/api/users/companies")  # creates nothing; B has no row yet
    resp_b = client.get(f"/api/users/companies/{a['id']}/jobs")
    assert resp_b.status_code == 403


# --- GET /jobs — the Recent-feed union ---------------------------------------


def test_all_owned_jobs_returns_every_board_the_caller_owns(client, db_conn, monkeypatch):
    """The owner's bug: custom jobs were reachable ONLY from a company's own trend
    page. This is the union endpoint the Recent feed calls."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    one = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    # A second board for the same user, created directly so the fixture does not
    # have to mock a second ATS.
    user_id = _user_id(db_conn, "a@example.com")
    two = svc.add_custom_company(
        db_conn, user_id=user_id, ats="lever", board_token="acme",
        provider_config={}, display_name="Acme", submitted_url="https://x",
        normalized_url="https://x",
    )
    _seed_job_for(db_conn, one["id"], "u1")
    _seed_job_for(db_conn, two["id"], "u2")

    resp = client.get("/api/users/companies/jobs")
    assert resp.status_code == 200, resp.text
    got = {(j["sourceId"], j["id"]) for j in resp.json()}
    assert (custom(one["id"]), "u1") in got
    assert (custom(two["id"]), "u2") in got


def test_all_owned_jobs_is_empty_for_a_signed_in_non_owner(client, db_conn, monkeypatch):
    """The leak that matters most: B is authenticated, so the endpoint answers —
    but the company set is derived from B's OWN ownership rows, so A's private
    jobs are not in it."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    a = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    _seed_job_for(db_conn, a["id"], "secret-1")

    _login(client, "auth0|B", "b@example.com")
    _user_id(db_conn, "b@example.com")  # B exists as a user, owns nothing
    resp = client.get("/api/users/companies/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_all_owned_jobs_never_serves_a_public_company(client, db_conn):
    """A contrived ownership row pointing at a PUBLIC company must not smuggle
    that company's jobs onto a private read path (mirror of the purge guard)."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES ('pub-feed', 'Pub', 'greenhouse', 'pub', TRUE, 'public')"
        ).format(sql.Identifier("companies"))
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES ('pf1', 'Eng', 'pub-feed', 'https://x/1', "
            "%s, '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', 'OPEN')"
        ).format(sql.Identifier("job_listings")),
        (custom("pub-feed"),),
    )
    db_conn.commit()
    _login(client, "auth0|P", "p@example.com")
    user_id = _user_id(db_conn, "p@example.com")
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) "
            "VALUES (%s, 'pub-feed', 'greenhouse:pub-feed')"
        ).format(sql.Identifier("user_companies")),
        (user_id,),
    )
    db_conn.commit()

    resp = client.get("/api/users/companies/jobs")
    assert resp.status_code == 200
    assert [j["id"] for j in resp.json()] == []


def test_all_owned_jobs_filters_by_status(client, db_conn, monkeypatch):
    _login(client, "auth0|S", "s@example.com")
    _install_greenhouse(monkeypatch, [1])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    _seed_job_for(db_conn, added["id"], "open-1", status="OPEN")
    _seed_job_for(db_conn, added["id"], "closed-1", status="CLOSED")

    ids = {j["id"] for j in client.get(
        "/api/users/companies/jobs", params={"status": "OPEN"}
    ).json()}
    assert "open-1" in ids and "closed-1" not in ids


def test_all_owned_jobs_pages_by_keyset_and_stops_on_a_short_page(
    client, db_conn, monkeypatch
):
    """Same ``since``/``cursor``/``X-Next-Cursor`` contract as ``GET /api/jobs``,
    so the frontend's existing keyset walk drives both halves of the feed. The
    ABSENCE of the header is the only end-of-walk signal — a short page that
    still carried one would loop forever."""
    _login(client, "auth0|K", "k@example.com")
    _install_greenhouse(monkeypatch, [1])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    for n, stamp in enumerate(
        ["2025-03-01T00:00:00Z", "2025-02-01T00:00:00Z", "2025-01-01T00:00:00Z"]
    ):
        _seed_job_for(db_conn, added["id"], f"k{n}", first_seen_at=stamp)

    page1 = client.get(
        "/api/users/companies/jobs",
        params={"since": "2020-01-01T00:00:00Z", "limit": 2},
    )
    assert page1.status_code == 200
    assert [j["id"] for j in page1.json()] == ["k0", "k1"]
    token = page1.headers.get("X-Next-Cursor")
    assert token, "a full page must mint the next-page token"

    page2 = client.get(
        "/api/users/companies/jobs",
        params={"since": "2020-01-01T00:00:00Z", "limit": 2, "cursor": token},
    )
    assert [j["id"] for j in page2.json()] == ["k2"]
    assert "X-Next-Cursor" not in page2.headers, "a short page is the end of the walk"


def test_all_owned_jobs_rejects_a_malformed_cursor(client, monkeypatch):
    """Fail loud: a silently-ignored cursor restarts the walk at page 1 with a
    200, which the client cannot tell from a honoured one."""
    _login(client, "auth0|K", "k@example.com")
    resp = client.get("/api/users/companies/jobs", params={"cursor": "not-a-cursor"})
    assert resp.status_code == 422
    resp_since = client.get("/api/users/companies/jobs", params={"since": "2025-01-01"})
    assert resp_since.status_code == 422


# --- Non-ATS / empty board ----------------------------------------------------


def test_non_ats_url_returns_422_and_records_unsupported(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")

    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no ats here</html>")

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.user_companies._http_client", factory)

    resp = client.post("/api/users/companies", json={"url": "https://careers.acme.test/jobs"})
    assert resp.status_code == 422
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'unsupported'") == 1


def test_resolvable_board_with_zero_jobs_is_422(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [])  # board resolves but has no jobs

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert resp.status_code == 422
    assert resp.json()["reason"] == "empty"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'empty'") == 1


# --- remove_owned_company defense-in-depth guard ------------------------------


def test_remove_owned_company_never_purges_a_public_company(client, db_conn):
    """FIX 3, now load-bearing twice over: a public company id reaching this path
    as the 'last owner' must lose ONLY the ownership link. Under the old code the
    worst case was a disabled public board; under a hard delete it would be a
    curated board and its jobs deleted outright."""
    cur = db_conn.cursor()
    # A public company + a contrived ownership row pointing at it.
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES ('pub-guard', 'Pub', 'greenhouse', 'pub', TRUE, 'public')"
        ).format(sql.Identifier("companies"))
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES ('uguard', 'auth0|uguard', 'g@example.com', '2025-01-01', '2025-01-01')"
        ).format(sql.Identifier("users"))
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) "
            "VALUES ('uguard', 'pub-guard', 'greenhouse:pub')"
        ).format(sql.Identifier("user_companies"))
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES ('pg1', 'Eng', 'pub-guard', 'https://x/1', "
            "'greenhouse_api', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', 'OPEN')"
        ).format(sql.Identifier("job_listings"))
    )
    db_conn.commit()

    outcome = svc.remove_owned_company(db_conn, "uguard", "pub-guard")

    assert outcome == "unlinked"
    cur.execute("SELECT enabled FROM companies WHERE id = 'pub-guard'")
    row = cur.fetchone()
    assert row is not None, "public company must not be deleted"
    assert row["enabled"] is True, "public company must stay enabled"
    cur.execute("SELECT count(*) AS n FROM job_listings WHERE company = 'pub-guard'")
    assert int(cur.fetchone()["n"]) == 1, "public company's jobs must survive"
    # The link itself IS removed — that part is the caller's own row.
    cur.execute(
        "SELECT count(*) AS n FROM user_companies WHERE company_id = 'pub-guard'"
    )
    assert int(cur.fetchone()["n"]) == 0


# --- Feature flag -------------------------------------------------------------


def test_flag_off_returns_503(client, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    monkeypatch.setattr(settings, "custom_company_sources_enabled", False)
    assert client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).status_code == 503
    assert client.get("/api/users/companies").status_code == 503
    assert client.delete("/api/users/companies/u-x").status_code == 503
    assert client.get("/api/users/companies/u-x/jobs").status_code == 503
    assert client.get("/api/users/companies/jobs").status_code == 503


# --- E7 Phase 3b: non-ATS URL → async discovery (202) behind the sub-flag ------

_NON_ATS_URL = "https://acme.example/careers"


def _patch_no_ats(monkeypatch, final_url: str = _NON_ATS_URL):
    from api.services.ats_discovery import DiscoveryResult

    async def _fake_discover_ats(url, http, *, deadline):
        return DiscoveryResult(
            candidate=None, via="unsupported", hops=(), final_url=final_url,
            reason="no_ats_detected",
        )

    monkeypatch.setattr("api.routers.user_companies.discover_ats", _fake_discover_ats)


def _capture_defer(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def _fake_defer(*, user_id, submitted_url, normalized_url, display_name):
        calls.append({
            "user_id": user_id, "submitted_url": submitted_url,
            "normalized_url": normalized_url, "display_name": display_name,
        })

    monkeypatch.setattr("api.routers.user_companies._defer_discovery", _fake_defer)
    return calls


def test_non_ats_url_enqueues_discovery_202(client, db_conn, monkeypatch):
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "discovery_pending"
    assert body["finalUrl"] == _NON_ATS_URL
    # The placeholder's id rides back on the 202 (E7 unit 3). Without it the caller can
    # only find the board it just added by diffing the list, so the "one-time setup"
    # notice could never point at the row now narrating its own progress.
    assert body["id"].startswith("u-")
    assert body["sourceId"] == custom(body["id"])

    # The one-time discovery task was enqueued exactly once, with the final URL.
    assert len(calls) == 1
    assert calls[0]["normalized_url"] == _NON_ATS_URL
    assert calls[0]["display_name"] == "acme.example"
    # A discovery_pending attempt row was recorded (§7).
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'discovery_pending'") == 1
    # A PROVISIONAL 'discovering' companies row now exists so the list shows the
    # board as "Setting up…" immediately — DISABLED (no scraping) and script-less
    # until the discovery task flips it to tracked or refused.
    cur = db_conn.cursor()
    cur.execute(
        "SELECT health_state, enabled, next_run_at, board_token FROM companies "
        "WHERE visibility = 'user'"
    )
    placeholder = cur.fetchone()
    assert placeholder is not None
    assert placeholder["health_state"] == "discovering"
    assert placeholder["enabled"] is False
    assert placeholder["next_run_at"] is None
    assert placeholder["board_token"] == _NON_ATS_URL
    assert _count(db_conn, "company_scripts") == 0


def test_non_ats_url_without_subflag_stays_422_unsupported(client, db_conn, monkeypatch):
    # Sub-flag OFF (the default): the non-ATS branch keeps today's 422 unsupported;
    # discovery (and its spend) never runs.
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    _login(client, "auth0|B", "b@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "no_ats_detected"
    assert len(calls) == 0
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'unsupported'") == 1


def test_discovery_is_gated_by_exactly_one_flag(client, db_conn, monkeypatch):
    """The capture pivot collapsed the retired two-flag gate to ONE. Pinned by name
    because ``Settings.model_config`` sets ``extra="ignore"`` — a typo'd env var leaves
    the flag silently False — and because the old pair produced a misleading "No
    supported ATS board" 422 when only one of them was off.

    With the single flag OFF: 422, no provisional row, no enqueue, no browser, no LLM."""
    assert hasattr(settings, "custom_company_discovery_enabled")
    assert not hasattr(settings, "browser_agent_enabled"), (
        "browser_agent_enabled was retired with the Stagehand tier"
    )
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    _login(client, "auth0|K", "k@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "no_ats_detected"
    assert len(calls) == 0                                          # nothing enqueued
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0  # no placeholder


def test_two_users_same_url_get_per_user_discovery_locks(monkeypatch):
    """FIX 5: the discovery queueing_lock is per-user, so two different users adding
    the SAME non-ATS URL each get their own discovery run (a URL-only lock made user
    B's defer collide → 500 + a wedged 'discovering' row)."""
    import asyncio

    from api.routers.user_companies import _defer_discovery
    import api.tasks.discover_custom_company as task_mod

    seen_locks: list[str] = []

    class _Configured:
        async def defer_async(self, **kwargs):
            return None

    def _fake_configure(*, queueing_lock):
        seen_locks.append(queueing_lock)
        return _Configured()

    monkeypatch.setattr(task_mod.discover_custom_company, "configure", _fake_configure)

    async def _drive() -> None:
        for user_id in ("user-a", "user-b"):
            await _defer_discovery(
                user_id=user_id, submitted_url="https://acme.example/careers",
                normalized_url=_NON_ATS_URL, display_name="acme.example",
            )

    asyncio.run(_drive())

    assert seen_locks == [
        f"discover:user-a:{_NON_ATS_URL}",
        f"discover:user-b:{_NON_ATS_URL}",
    ]
    assert seen_locks[0] != seen_locks[1]   # distinct → no cross-user collision


# --- E7 unit 3: the discovery checklist rides the list response ----------------


def _steps(company: dict) -> dict:
    return {step["key"]: step for step in company["discovery"]["steps"]}


def test_a_discovering_row_lists_with_its_checklist_already_narrating(
    client, db_conn, monkeypatch
):
    """The whole point of DECISION D2: the checklist arrives on the SAME poll the list
    already runs, so no second polling channel exists. And the 202 row is narrating
    before the worker touches it — otherwise it is a bare "Setting up…" badge, i.e. the
    spinner this replaced."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    _capture_defer(monkeypatch)
    client.post("/api/users/companies", json={"url": _NON_ATS_URL})

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["healthState"] == "discovering"
    # camelCase on the wire, via the model's `to_camel` generator.
    assert company["discovery"]["outcome"] == "running"
    assert company["discovery"]["liveViewUrl"] is None       # own-Chromium default (D4)
    assert _steps(company)["open_page"]["status"] == "active"
    assert [s["key"] for s in company["discovery"]["steps"]] == [
        "open_page", "find_feed", "verify_read", "ready"
    ]


def test_an_accepted_board_lists_its_four_ticks_and_a_job_preview(client, db_conn):
    """Success has to be legible: the specific result per step ("read 90 jobs") plus a
    few real jobs, so the user can tell this is their board (DECISION D3)."""
    _login(client, "auth0|A", "a@example.com")
    user_id = _user_id(db_conn, "a@example.com")

    ledger = dp.ProgressLedger()
    ledger.finish(dp.STEP_OPEN_PAGE, "opened acme.example — recorded 9 JSON request(s)")
    ledger.finish(dp.STEP_FIND_FEED, "found 3 candidate feed(s)")
    ledger.finish(dp.STEP_VERIFY_READ, "read 90 job(s)")
    ledger.finish(dp.STEP_READY, "reading the board's own feed directly — no browser needed")
    svc.add_discovered_company(
        db_conn, user_id=user_id, submitted_url=_NON_ATS_URL,
        normalized_url=_NON_ATS_URL, display_name="acme.example",
        script={"script_version": 1}, transport="http_json", oracle_kind="none",
        progress=ledger.snapshot(
            outcome=dp.OUTCOME_TRACKING,
            job_preview=[{"id": "1", "title": "Staff Engineer", "location": "Remote",
                          "url": "https://acme.example/jobs/1"}],
        ),
    )

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["discovery"]["outcome"] == "tracking"
    assert _steps(company)["verify_read"]["result"] == "read 90 job(s)"
    assert company["discovery"]["jobPreview"] == [
        {"title": "Staff Engineer", "location": "Remote",
         "url": "https://acme.example/jobs/1"}
    ]


def test_a_refused_board_lists_the_named_step_that_failed(client, db_conn):
    """"Not trackable" alone is a dead end. The failed step is what turns it into "we
    found the feed, but couldn't confirm the results match" — and the audit row that
    also carries the reason is not readable by ANY endpoint, so this is the only path
    from a refusal to the user."""
    _login(client, "auth0|A", "a@example.com")
    user_id = _user_id(db_conn, "a@example.com")

    ledger = dp.ProgressLedger()
    ledger.finish(dp.STEP_OPEN_PAGE, "opened acme.example — recorded 9 JSON request(s)")
    ledger.finish(dp.STEP_FIND_FEED, "found 3 candidate feed(s)")
    ledger.fail(dp.STEP_VERIFY_READ,
                "only 1 of the 12 job(s) the browser saw came back from the replay")
    svc.record_discovery_refusal(
        db_conn, user_id=user_id, submitted_url=_NON_ATS_URL,
        normalized_url=_NON_ATS_URL, display_name="acme.example",
        reason="verifying we can read it: …",
        progress=ledger.snapshot(outcome=dp.OUTCOME_REFUSED),
    )

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["healthState"] == "refused"
    steps = _steps(company)
    assert steps["find_feed"]["status"] == "done"
    assert steps["verify_read"]["status"] == "failed"
    assert "came back from the replay" in steps["verify_read"]["result"]


def test_an_ats_companys_provider_config_never_leaks_as_a_checklist(
    client, db_conn, monkeypatch
):
    """``provider_config`` is shared with the ATS providers (Workday's baseUrl lives
    there). A row with no 'discovery' key must read as "no checklist", never as a
    half-parsed one and never by echoing the provider's own config back."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])
    client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["discovery"] is None
