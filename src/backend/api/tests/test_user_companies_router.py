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
from api.routers.user_companies import _discovery_display_name
from api.services.rate_limit import user_company_add_rate_limiter
from api.services.user_service import get_or_create_user
from scripts.shared.constants import custom

from .conftest import _insert_admin

GREENHOUSE_URL = "https://boards.greenhouse.io/duolingo"


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    """Pin BOTH E7 flags to the values these tests assume, rather than inheriting them.

    ``Settings`` loads ``.env.local``, which is untracked and developer-specific. A
    test that reads a flag it never set therefore behaves one way in CI (flag absent →
    the compiled-in default) and the opposite way on a machine whose ``.env.local``
    turns it on. That is exactly how ``test_non_ats_url_returns_422_and_records_unsupported``
    — a test whose whole premise is "discovery is OFF" — silently started running the
    discovery branch locally and 500ing on an unopened Procrastinate app.

    So: the parent flag ON (every test here is about the feature), and the discovery
    sub-flag OFF, which is its production default. Tests that are about discovery
    being on set it to ``True`` themselves inside the test body, which runs after this
    fixture and wins.
    """
    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)


@pytest.fixture(autouse=True)
def no_add_limits(monkeypatch):
    """Neutralise BOTH add limits for every test that is not about them.

    This module makes ~70 POSTs to ``/api/users/companies``, almost all as the same
    ``auth0|A``, in well under a minute. Left alone, the 10/60s burst limiter would
    429 the back half of the file and the 20/month cap would 422 it — neither of
    which is what any of those tests is asserting.

    Both are neutralised HERE rather than at their production defaults so the
    failure mode is loud: a limit test must set its own value, and one that forgets
    to sees "no limit at all" (an obviously wrong pass/fail) rather than inheriting a
    number some unrelated test happened to leave behind. The burst limiter is a
    process-wide singleton, so it is also RESET rather than only re-sized —
    ``_max`` alone would leave a previous test's timestamps in the bucket.

    The monthly cap is neutralised with a LARGE NUMBER, and it has to be: ``0`` used
    to mean unlimited and now means "no adds at all", so the old value would refuse
    every POST in this file rather than allowing them.
    """
    user_company_add_rate_limiter.reset()
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 1_000_000)
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1_000_000)
    yield
    user_company_add_rate_limiter.reset()


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


# --- boardUrl: WHERE this row is read from -------------------------------------
#
# The owner typed a NAME ("Cisco"), search picked a board, we tracked it — and the
# row never said which page it ended up reading. The link is computed server-side
# because the data is server-side: Workday's real host is in ``provider_config``,
# which the payload does not carry, so the frontend's own derivation could only
# ever cover the four providers whose token IS their board slug.


def _add_ats_company(db_conn, email: str, *, ats: str, token: str, config: dict) -> str:
    """A tracked ATS company with a real ``provider_config``, created by the same
    service the add endpoint calls. Workday and Eightfold cannot be added through
    ``POST`` here without mocking their whole probe, and what these tests are about
    is the READ, not the resolve."""
    created = svc.add_custom_company(
        db_conn,
        user_id=_user_id(db_conn, email),
        ats=ats,
        board_token=token,
        provider_config=config,
        display_name=token,
        submitted_url="https://example.test/careers",
        normalized_url="https://example.test/careers",
    )
    return str(created["id"])


def test_the_list_says_which_board_a_greenhouse_row_reads(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["boardUrl"] == "https://job-boards.greenhouse.io/duolingo"


def test_a_workday_row_now_gets_the_link_it_used_to_render_nothing_for(client, db_conn):
    """THE REPORTED BUG. ``board_token`` is the cosmetic tenant label (``cisco``) and
    names no host, so the frontend refused to guess and the row showed no source at
    all. ``provider_config`` has had the real board all along."""
    _login(client, "auth0|A", "a@example.com")
    _add_ats_company(
        db_conn, "a@example.com", ats="workday", token="cisco",
        config={
            "base_url": "https://cisco.wd5.myworkdayjobs.com",
            "tenant_slug": "cisco",
            "career_site_slug": "Cisco_Careers",
        },
    )

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["ats"] == "workday"
    assert company["boardUrl"] == (
        "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers"
    )


def test_an_eightfold_row_gets_its_tenant_key_back_on_the_wire(client, db_conn):
    """The other provider that rendered nothing. The tenant key is not derivable from
    the host (``netflix.net`` 404s while ``netflix.com`` does not), so it comes from
    ``provider_config`` or not at all."""
    _login(client, "auth0|A", "a@example.com")
    _add_ats_company(
        db_conn, "a@example.com", ats="eightfold", token="netflix",
        config={"tenant_host": "explore.jobs.netflix.net", "domain": "netflix.com"},
    )

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["boardUrl"] == (
        "https://explore.jobs.netflix.net/careers?domain=netflix.com"
    )


def test_the_add_response_carries_the_same_link_the_list_will(client, db_conn, monkeypatch):
    """The 201 body renders the success card, so it cannot be the one response missing
    the link every later read of the same row carries."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert added["boardUrl"] == company["boardUrl"]
    assert added["boardUrl"] == "https://job-boards.greenhouse.io/duolingo"


def test_a_discovered_row_links_the_page_the_user_actually_pasted(client, db_conn):
    _login(client, "auth0|A", "a@example.com")
    user_id = _user_id(db_conn, "a@example.com")
    svc.add_discovering_placeholder(
        db_conn, user_id=user_id, submitted_url=_NON_ATS_URL,
        normalized_url=_NON_ATS_URL, display_name="acme.example",
    )

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["boardUrl"] == _NON_ATS_URL


def test_a_row_whose_config_we_cannot_vouch_for_carries_no_link_at_all(client, db_conn):
    """NULL is a real answer and the UI renders nothing for it. A Workday row with a
    config we did not write gets no link rather than a confident 404."""
    _login(client, "auth0|A", "a@example.com")
    _add_ats_company(
        db_conn, "a@example.com", ats="workday", token="acme", config={},
    )

    (company,) = client.get("/api/users/companies").json()["companies"]
    assert company["boardUrl"] is None


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
    # THE SIDE EFFECT THIS TEST WAS MISSING. "422 and no side effects" has to include
    # the broker: the discovery gate is what stands between a flag-off refusal and a
    # ``defer_async`` on Procrastinate, and if that enqueue ever moved above the gate
    # the two DB assertions below would still pass while a real user with discovery
    # off got a queued job they never asked for. (``_capture_defer`` is defined lower
    # in this module; it is a module-level function, so the order does not matter.)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": "https://careers.acme.test/jobs"})
    assert resp.status_code == 422, resp.text
    assert calls == []
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


# --- P2 dedupe: a board we already publish is not a board to copy -------------
#
# The case the owner hit: he tracks Spotify publicly (``lever:spotify``) AND added it
# privately, so one company had two scrapers and two job sets. When a pasted URL
# resolves to a board we already publish, the add creates NOTHING and hands back the
# public company to link to.
#
# What these pin, in order: nothing is written; the audit still records the attempt;
# the override still works and stays idempotent afterwards; and the three matching
# rules that a naive ``(ats, board_token) =`` would get wrong.

ASHBY_URL = "https://jobs.ashbyhq.com/sierra"
WORKDAY_SLACK_URL = "https://salesforce.wd12.myworkdayjobs.com/Slack"


def _seed_public_company(
    db_conn,
    company_id: str,
    *,
    ats: str = "greenhouse",
    board_token: str,
    display_name: str | None = None,
    provider_config: str = "{}",
    enabled: bool = True,
) -> None:
    """One ``visibility='public'`` row — the fleet the dedupe SELECT reads."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, provider_config, "
            "enabled, visibility) VALUES (%s, %s, %s, %s, %s::jsonb, %s, 'public')"
        ).format(sql.Identifier("companies")),
        (company_id, display_name or company_id, ats, board_token,
         provider_config, enabled),
    )
    db_conn.commit()


def _install_recording_transport(monkeypatch) -> list[str]:
    """404 everything, and record every outbound URL the add path asks for.

    The dedupe branch sits BEFORE the probe, so a hit must cost zero requests. A
    404-everything transport also makes the regression loud rather than silent: if
    the branch stopped firing, the probe would run and the add would come back 422
    ``probe_failed`` instead of 200.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(404)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.user_companies._http_client", factory)
    return seen


def test_a_board_we_already_publish_links_instead_of_adding(
    client, db_conn, monkeypatch
):
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "duolingo", board_token="duolingo",
                         display_name="Duolingo")
    requests_made = _install_recording_transport(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "already_public"
    assert body["companyId"] == "duolingo"
    assert body["displayName"] == "Duolingo"
    assert body["finalUrl"] == GREENHOUSE_URL
    assert "Duolingo" in body["detail"]

    # ROW COUNTS, not the response shape: the whole point of this branch is that
    # the four rows an add normally writes are not written.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "user_companies") == 0
    assert _count(db_conn, "company_scripts") == 0
    assert _count(db_conn, "job_listings") == 0
    # ...and the public row is untouched — no ownership, no second scraper.
    assert _count(db_conn, "companies", "WHERE id = 'duolingo'") == 1

    # The audit stays complete, and points at the PUBLIC company it resolved to.
    assert _count(
        db_conn, "company_add_attempts",
        "WHERE outcome = 'already_public' AND company_id = 'duolingo' "
        "AND resolved_ats = 'greenhouse' AND board_token = 'duolingo'",
    ) == 1

    # No probe, no outbound request at all.
    assert requests_made == []


def test_track_anyway_adds_the_private_copy_and_stays_idempotent(
    client, db_conn, monkeypatch
):
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "duolingo", board_token="duolingo",
                         display_name="Duolingo")
    _install_greenhouse(monkeypatch, [1, 2, 3])

    optin = client.post(
        "/api/users/companies", json={"url": GREENHOUSE_URL, "trackAnyway": True}
    )
    assert optin.status_code == 201, optin.text
    company_id = optin.json()["id"]
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1

    # And the SECOND add of that URL — without the override — must still resolve to
    # THEIR row. The dedupe check sits after the idempotent branch precisely so the
    # endpoint does not stop being idempotent for the users who opted in.
    again = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == company_id
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1


def test_a_board_we_do_not_publish_is_added_as_usual(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    # A public Greenhouse row for a DIFFERENT board. The check must key on the
    # board, not on "we have some public Greenhouse companies".
    _seed_public_company(db_conn, "someoneelse", board_token="someoneelse")
    _install_greenhouse(monkeypatch, [1, 2, 3])

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 201, resp.text
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_a_mixed_case_ashby_token_still_matches(client, db_conn, monkeypatch):
    """8 of the 58 public Ashby rows store ``Sierra`` / ``Linear`` / ``GigaML``.

    The resolver lowercases every Ashby token, so an ``=`` comparison would miss
    all eight — the exact class of near-miss that makes a dedupe look like it works
    until it quietly does not.
    """
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "sierra", ats="ashby", board_token="Sierra",
                         display_name="Sierra")
    _install_recording_transport(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": ASHBY_URL})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "sierra"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0


def test_a_workday_board_matches_on_its_tenant_not_on_our_company_id(
    client, db_conn, monkeypatch
):
    """Public Workday rows keep OUR company id in ``board_token`` (``slack``).

    The resolver emits the tenant (``salesforce``), so all 11 public Workday rows
    would miss on ``board_token``. The identity is in ``provider_config``.
    """
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(
        db_conn, "slack", ats="workday", board_token="slack", display_name="Slack",
        provider_config=(
            '{"base_url": "https://salesforce.wd12.myworkdayjobs.com", '
            '"tenant_slug": "salesforce", "career_site_slug": "Slack"}'
        ),
    )
    _install_recording_transport(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": WORKDAY_SLACK_URL})

    assert resp.status_code == 200, resp.text
    assert resp.json()["displayName"] == "Slack"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0


def test_another_career_site_on_the_same_workday_tenant_is_not_that_company(
    client, db_conn, monkeypatch
):
    """``salesforce`` hosts ``/Slack`` and other career sites.

    Matching on the tenant alone would answer a Salesforce URL with "we already
    track Slack" — a confidently wrong link to a different company's chart.
    """
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(
        db_conn, "slack", ats="workday", board_token="slack", display_name="Slack",
        provider_config=(
            '{"base_url": "https://salesforce.wd12.myworkdayjobs.com", '
            '"tenant_slug": "salesforce", "career_site_slug": "Slack"}'
        ),
    )
    _install_recording_transport(monkeypatch)

    resp = client.post(
        "/api/users/companies",
        json={"url": "https://salesforce.wd12.myworkdayjobs.com/External"},
    )

    # Not a dedupe hit — it falls through to the normal add path, where the
    # 404-everything transport fails the probe. What matters is that it is NOT a
    # 200 naming Slack.
    assert resp.status_code == 422, resp.text
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_a_disabled_public_board_is_not_offered_as_the_answer(
    client, db_conn, monkeypatch
):
    """A disabled public row is a board we have STOPPED reading.

    Pointing someone at a chart that no longer updates is worse than letting them
    track their own copy, so ``enabled`` is part of the match.
    """
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "duolingo", board_token="duolingo", enabled=False)
    _install_greenhouse(monkeypatch, [1, 2, 3])

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 201, resp.text
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1


def test_another_users_private_board_is_never_offered_as_the_answer(
    client, db_conn, monkeypatch
):
    """P1 is DEFERRED, and this is that deferral in executable form.

    User A privately tracks a board; user B pastes the same URL. B must get their
    own private company, not a pointer at A's — the check reads the PUBLIC fleet
    only. Dropping ``visibility = 'public'`` from the SELECT would leak the
    existence (and the display name) of one user's private board to another.
    """
    _install_greenhouse(monkeypatch, [1, 2, 3])

    _login(client, "auth0|A", "a@example.com")
    assert client.post(
        "/api/users/companies", json={"url": GREENHOUSE_URL}
    ).status_code == 201

    _login(client, "auth0|B", "b@example.com")
    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 201, resp.text
    assert resp.json()["ats"] == "greenhouse"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 2
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_a_public_board_owned_by_another_user_is_still_a_link_for_this_one(
    client, db_conn, monkeypatch
):
    """The check is against the PUBLIC fleet, not against anyone's private list.

    User A opted into a private copy; that must not change the answer user B gets.
    """
    _seed_public_company(db_conn, "duolingo", board_token="duolingo",
                         display_name="Duolingo")
    _install_greenhouse(monkeypatch, [1, 2, 3])

    _login(client, "auth0|A", "a@example.com")
    optin = client.post(
        "/api/users/companies", json={"url": GREENHOUSE_URL, "trackAnyway": True}
    )
    assert optin.status_code == 201

    _login(client, "auth0|B", "b@example.com")
    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "duolingo"
    # Still exactly A's one private row.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1


# --- the first harvest of an ATS add (E7) -------------------------------------
#
# What this section pins is the owner's bug: he pasted a Workday careers URL, the page
# said "Found 1,200 open jobs", and the row it created then sat at "Successfully
# tracking · 0 open jobs · Not yet checked" — because the ATS fast path created the row
# due and left the reading to the ``*/15 * * * *`` claim tick. Discovery already
# enqueued its own first harvest; this is the SAME helper wired into the fast path, so
# the two can never disagree about the queueing lock or about what "already scheduled"
# means.


def _record_defers(monkeypatch, result: str = "deferred") -> list[str]:
    """Capture every ``fetch_custom_company`` enqueue the add path makes.

    Patched on ``claim_custom_companies`` — the ONE module that enqueues a custom
    harvest. The router reaches it through ``start_first_harvest``, which resolves
    ``defer_fetch`` off that module at call time, so this sees the real path rather
    than a stub standing in for it.
    """
    import api.tasks.claim_custom_companies as claim_mod

    calls: list[str] = []

    # **kwargs absorbs the `queue=` the first-harvest path now passes so it can
    # land on the reserved interactive lane; which queue it targets is asserted
    # in test_worker_lanes.py, not here.
    async def _defer(company_id: str, **_kwargs: object) -> str:
        calls.append(company_id)
        return result

    monkeypatch.setattr(claim_mod, "defer_fetch", _defer)
    return calls


def _seconds_until_next_run(db_conn, company_id: str) -> float:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        "SELECT EXTRACT(EPOCH FROM (next_run_at - now())) AS s "
        "FROM companies WHERE id = %s",
        (company_id,),
    )
    return float(cur.fetchone()["s"])


def _assert_rescheduled_a_full_cadence_out(db_conn, company_id: str) -> None:
    """The property these tests actually mean: the row was pushed a whole cadence ±
    jitter ahead, i.e. it is **not left due** and the `*/15` claim tick cannot see it.

    Derived from the two constants, never spelled as a literal. These assertions used
    to read ``> 22 * 3600`` — "22 hours", which was a stand-in for "a 24 h cadence minus
    the ±90 min jitter" and silently became a *cadence* assertion. When the cadence moved
    to 1 h the number was wrong in a way that says nothing about what the tests are for
    (one is about the discovery flag, the other about the enqueue interlock). Expressed
    this way, a future cadence change moves both bounds automatically and a genuinely
    broken reschedule — the row left due — still fails.
    """
    import api.tasks.claim_custom_companies as claim_mod

    cadence_s = svc.DEFAULT_CADENCE_HOURS * 3600
    spread_s = cadence_s * claim_mod._JITTER_FRACTION
    actual_s = _seconds_until_next_run(db_conn, company_id)

    # -5 s / +5 s: the read-back's now() is a few ms later than the UPDATE's, so the
    # measured offset sits marginally inside the arithmetic window.
    assert cadence_s - spread_s - 5 <= actual_s <= cadence_s + spread_s + 5, (
        f"expected {company_id} rescheduled ~{cadence_s}s out (±{spread_s}s jitter), "
        f"got {actual_s}s — a value near zero means the row was left DUE"
    )


def test_an_ats_add_enqueues_its_first_harvest_immediately(client, db_conn, monkeypatch):
    """THE FIX. Without it the company is tracked, green, and empty until the next
    15-minute tick — which reads as "we looked and your board has no jobs" directly
    under a preview that just said we found some."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])
    calls = _record_defers(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 201, resp.text
    assert calls == [resp.json()["id"]]


def test_the_immediate_harvest_takes_the_row_off_the_claim_ticks_list(
    client, db_conn, monkeypatch
):
    """THE INTERLOCK, primary half. ``add_custom_company`` leaves ``next_run_at =
    now()``; once the harvest is on the broker the row is pushed a full cadence ± jitter
    ahead, so the tick — which selects on ``next_run_at <= now()`` — cannot even see it.
    That is what makes a second, concurrent harvest of the same board impossible rather
    than merely unlikely."""
    import api.tasks.claim_custom_companies as claim_mod

    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    _record_defers(monkeypatch)

    company_id = client.post(
        "/api/users/companies", json={"url": GREENHOUSE_URL}
    ).json()["id"]

    _assert_rescheduled_a_full_cadence_out(db_conn, company_id)
    assert company_id not in claim_mod._claim_due_companies(db_conn, 10)


def test_the_first_harvest_is_not_gated_by_the_discovery_flag(
    client, db_conn, monkeypatch
):
    """THE TRAP. ``custom_company_discovery_enabled`` is OFF in production, and an ATS
    board has nothing to do with discovery — it was resolved and probed for free. Gating
    the immediate harvest on that flag (which the discovered ``browser_fetch`` tier DOES
    need, because discovery is the only thing that creates it) would leave every ATS add
    exactly as broken as it was, in the default configuration."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2])
    calls = _record_defers(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 201, resp.text
    assert calls == [resp.json()["id"]]
    # …and the reschedule that goes with it: the harvest was queued AND the row pushed
    # a cadence out. Property, not a literal — see the helper.
    _assert_rescheduled_a_full_cadence_out(db_conn, resp.json()["id"])


def test_a_re_add_of_a_tracked_board_starts_no_second_harvest(
    client, db_conn, monkeypatch
):
    """Re-pasting a URL already tracked resolves to the existing row (200). It must NOT
    harvest again, or the add form becomes a manual scrape button anyone can hold down —
    and the second run would land on a board whose ``next_run_at`` says it is not due."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])
    calls = _record_defers(monkeypatch)

    first = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    second = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert (first.status_code, second.status_code) == (201, 200)
    assert calls == [first.json()["id"]]


def test_a_racing_double_add_starts_only_one_harvest(client, db_conn, monkeypatch):
    """The other half of idempotency, and the only one the 200 branch cannot cover: two
    adds of the same board in flight together. The loser's pre-check sees no company, so
    it reaches ``add_custom_company`` and lands on the UNIQUE race backstop — which
    resolves to the row the winner just created AND already started a harvest for.
    Reading ``created`` is what tells those two return shapes apart."""
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2])
    calls = _record_defers(monkeypatch)

    winner = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    # Simulate the race: the SECOND request's ownership pre-check runs before the
    # winner's INSERT is visible to it, so it proceeds as if the board were new. Only
    # the first lookup is blinded; the service's own backstop lookup must still find
    # the row, which is what makes this the race and not just a missing company.
    real_lookup = svc.find_owned_company_by_source_key
    seen: list[int] = []

    def _blind_once(conn, user_id, source_key):
        seen.append(1)
        if len(seen) == 1:
            return None
        return real_lookup(conn, user_id, source_key)

    monkeypatch.setattr(svc, "find_owned_company_by_source_key", _blind_once)

    loser = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert loser.json()["id"] == winner.json()["id"]
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert calls == [winner.json()["id"]]


def test_a_broker_that_will_not_take_the_job_still_adds_the_company(
    client, db_conn, monkeypatch
):
    """The safe direction, twice over. The user is waiting on this response: a broker
    problem must not turn a perfectly good add into a 500. And it must not cost the
    board a cadence either — the row stays DUE, so the next tick runs it exactly as it
    did before the immediate enqueue existed. Pushing ``next_run_at`` on a failed defer
    would silently trade a 15-minute wait for a 24-hour one."""
    import api.tasks.claim_custom_companies as claim_mod

    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    _record_defers(monkeypatch, result="failed")

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 201, resp.text
    company_id = resp.json()["id"]
    assert _seconds_until_next_run(db_conn, company_id) < 60
    assert company_id in claim_mod._claim_due_companies(db_conn, 10)


def test_an_enqueue_that_explodes_never_fails_the_add(client, db_conn, monkeypatch):
    """``defer_fetch`` narrows to broker/database errors, so anything else — the
    ``AppNotOpen`` a mis-wired connector raises, an import error, a new Procrastinate
    exception — arrives here unswallowed. The company is already committed at that
    point; the ONLY acceptable outcome is the pre-existing one, a tracked row the claim
    tick will read."""
    import api.tasks.claim_custom_companies as claim_mod

    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])

    async def _boom(company_id: str, **_kwargs: object) -> str:
        raise RuntimeError("broker is on fire")

    monkeypatch.setattr(claim_mod, "defer_fetch", _boom)

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})

    assert resp.status_code == 201, resp.text
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _seconds_until_next_run(db_conn, resp.json()["id"]) < 60


def test_a_claim_tick_right_after_an_add_queues_no_second_harvest(
    client, db_conn, monkeypatch
):
    """END TO END: add, then fire the real periodic tick. Exactly ONE
    ``fetch_custom_company`` exists for the board — the tick is a no-op for it, not a
    duplicate."""
    import asyncio
    import os

    import api.tasks.claim_custom_companies as claim_mod

    # The tick opens its OWN connection off ``settings.database_url`` (it runs on the
    # worker, not on a request), so point it at the schema this test's fixture built.
    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    calls = _record_defers(monkeypatch)

    company_id = client.post(
        "/api/users/companies", json={"url": GREENHOUSE_URL}
    ).json()["id"]

    # Park every OTHER row this module-scoped schema accumulated, so the tick's budget
    # of 3 cannot be spent elsewhere and mask the result.
    cur = db_conn.cursor()
    cur.execute("UPDATE companies SET next_run_at = NULL WHERE id <> %s", (company_id,))
    db_conn.commit()

    assert asyncio.run(claim_mod.claim_custom_companies(timestamp=1)) == 0
    assert calls.count(company_id) == 1


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
    # The label the row is stored under is derived from the host, not the raw
    # host itself — "acme.example" reads like a URL, "Acme" reads like a company.
    assert calls[0]["display_name"] == "Acme"
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


# --- A URL we could not even READ: no discovery, no audit row, no slot ---------
#
# THE REGRESSION THESE PIN, and it is one this endpoint's own contract created the
# moment the Add Companies page stopped calling `/api/companies/resolve` first.
#
# The page used to preview a URL through the resolve endpoint (which persists nothing
# and charges nothing) and only POST here on `no_ats_detected`. Every OTHER resolver
# reason — a url_guard refusal, a DNS or connection failure, a redirect loop — stayed a
# plain client-side error that never reached this route. One press now sends every URL
# straight here, so both properties the client-side gate bought have to be bought on
# this side:
#
#   * the discovery gate is `if discovery_enabled and result.final_url`, and
#     `final_url` falls back to the URL the user typed — so `https://192.168.1.1/x`
#     would insert a provisional row and enqueue a capture run for an address the
#     resolver had just refused to fetch; and
#   * `company_add_attempts` is what the 20-a-month cap counts, so a mistyped scheme
#     would cost 1/20 of somebody's month.
#
# `http://` needs no mock and no network: `resolve_ats_url` finds no ATS in it, and
# `guarded_get` raises `scheme_not_https` before a byte leaves the process.
_UNREADABLE_URL = "http://careers.acme.test/jobs"


def test_a_url_we_could_not_read_starts_no_discovery(client, db_conn, monkeypatch):
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|UNREAD", "unread@example.com")
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _UNREADABLE_URL})

    assert resp.status_code == 422, resp.text
    # The resolver's OWN code, passed through — that is what the frontend's
    # `describeResolveError` keys off to say "The address must use HTTPS".
    assert resp.json()["reason"] == "scheme_not_https", resp.text
    assert calls == [], "a URL we refused to fetch must never reach the capture queue"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0


def test_a_url_we_could_not_read_spends_no_monthly_slot(client, db_conn, monkeypatch):
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|UNREAD2", "unread2@example.com")
    _capture_defer(monkeypatch)

    before = _quota(client)["used"]
    for _ in range(3):
        assert client.post(
            "/api/users/companies", json={"url": _UNREADABLE_URL}
        ).status_code == 422

    assert _quota(client)["used"] == before, (
        "three typos must not cost three of this month's twenty adds"
    )
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'unsupported'") == 0


def test_an_unreachable_host_is_refused_the_same_way(client, db_conn, monkeypatch):
    """The transport half of the same rule — a domain that does not resolve.

    Same verdict as the guard refusal above: we never read a page, so there is no
    verdict about a board to record and nothing for discovery to work on."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|DNS", "dns@example.com")
    calls = _capture_defer(monkeypatch)

    from api.services.ats_discovery import DiscoveryResult

    async def _fake(url, http, *, deadline):
        return DiscoveryResult(
            candidate=None, via="unsupported", hops=(), final_url=url,
            reason="dns_resolution_failed",
        )

    monkeypatch.setattr("api.routers.user_companies.discover_ats", _fake)

    resp = client.post("/api/users/companies", json={"url": "https://nope.invalid/x"})

    assert resp.status_code == 422
    assert resp.json()["reason"] == "dns_resolution_failed"
    assert calls == []
    assert _count(db_conn, "company_add_attempts") == 0


def test_a_page_we_DID_read_still_charges_and_still_discovers(
    client, db_conn, monkeypatch
):
    """The other side of the line, and why it is drawn where it is.

    `no_ats_detected` means we fetched the page, read it, and found no board we
    support. That is a real verdict about a real board, it is exactly what one-time
    discovery exists for, and starting one spends a headless Chromium session and an
    LLM call — so it records an attempt and it charges. This must NOT be "fixed"."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|CHARGED", "charged@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    before = _quota(client)["used"]
    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1
    assert _quota(client)["used"] == before + 1


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
        "open_page", "find_feed", "verify_read", "ready", "first_scan"
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
    # Discovery PROMOTES the provisional row the add path inserted; it no longer
    # creates one of its own (a missing placeholder now means the user removed the
    # board mid-run). So seed the placeholder exactly as the 202 add does.
    svc.add_discovering_placeholder(
        db_conn, user_id=user_id, submitted_url=_NON_ATS_URL,
        normalized_url=_NON_ATS_URL, display_name="acme.example",
    )
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
    svc.add_discovering_placeholder(
        db_conn, user_id=user_id, submitted_url=_NON_ATS_URL,
        normalized_url=_NON_ATS_URL, display_name="acme.example",
    )
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


# --- the label a discovered company is stored under -----------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # The case that prompted this: a job card read "www.janestreet.com", which
        # looks like a URL nobody cleaned up rather than a company.
        ("https://www.janestreet.com/join-jane-street/open-roles/", "Janestreet"),
        # Stripping only `www.` would name this board "Jobs".
        ("https://jobs.uber.com/en/jobs/", "Uber"),
        ("https://careers.acme.co.uk/roles", "Acme"),      # compound suffix, not "Co"
        ("https://www.atlassian.com/company/careers/all-jobs", "Atlassian"),
        ("https://amazon.jobs/en/search", "Amazon"),       # noise label as the TLD
        ("https://jane-street.com/x", "Jane Street"),      # hyphens are word breaks
        ("https://jobs.example.com", "Example"),
        # THE DIRECTORY CASE. The host is Y Combinator's; the company is Raindrop's.
        # Naming this after the host gave one label to ~1,500 different boards.
        ("https://www.ycombinator.com/companies/raindrop/jobs", "Raindrop"),
        # The tenant slug gets the same hyphen treatment the host label gets.
        ("https://www.ycombinator.com/companies/wispr-flow/jobs", "Wispr Flow"),
        # Any directory host, not one we named: the shape is what is recognised.
        ("https://directory.example/employers/acme/jobs", "Acme"),
    ],
)
def test_discovery_display_name_reads_like_a_company(url, expected):
    assert _discovery_display_name(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        # Atlassian sits under `/company/`, but the next segment is a careers word, not
        # a tenant — this is the case that would have been named "Careers".
        ("https://www.atlassian.com/company/careers/all-jobs", "Atlassian"),
        # No directory segment at all.
        ("https://www.janestreet.com/join-jane-street/open-roles/", "Janestreet"),
        # A leaf under `/company/`: a directory URL points AT a tenant and keeps going,
        # so nothing following the slug means we decline rather than guess.
        ("https://acme.example/company/our-story", "Acme"),
        ("https://www.ycombinator.com/companies/raindrop", "Ycombinator"),
    ],
)
def test_a_path_only_names_a_company_when_it_is_a_directory(url, expected):
    """The path is asked first, but it answers rarely — three conditions, and every one
    of them is a wrong name that was measured against a board this repo already tracks.
    """
    assert _discovery_display_name(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        # No reliable way to split a run-together label — "Mongo Db" is worse than
        # "Mongodb", so we capitalise and stop. We must not invent word boundaries.
        ("https://www.mongodb.com/careers", "Mongodb"),
        # An IP literal has no registrable name; keep it verbatim rather than guess.
        ("http://192.168.1.1/jobs", "192.168.1.1"),
        # Nothing parseable at all falls back to what we were given.
        ("not-a-url", "not-a-url"),
    ],
)
def test_discovery_display_name_declines_to_invent(url, expected):
    assert _discovery_display_name(url) == expected


# --- E7 unit 11: the careers-host match for the ats='script' boards ------------
#
# Amazon / Apple / Google / Microsoft / TikTok are published with ``ats='script'``, a
# sentinel the ATS resolver never emits, so unit 9's ``(ats, board_token)`` dedupe
# cannot see them. Before this unit their careers URLs fell straight through to
# one-time discovery — a Claude call and a headless Chromium session to build a
# private duplicate of a board on our own front page. These tests are the assertion
# that they no longer do.

#: The URLs the owner actually pasted, plus one per remaining script board.
_SCRIPT_BOARD_URLS = [
    ("https://jobs.careers.microsoft.com/global/en/search", "microsoft", "Microsoft"),
    ("https://www.amazon.jobs/en/search", "amazon", "Amazon"),
    ("https://jobs.apple.com/en-us/search", "apple", "Apple"),
    ("https://careers.google.com/", "google", "Google"),
    ("https://lifeattiktok.com/search", "tiktok", "TikTok"),
]

#: The five published rows, exactly as prod holds them.
_SEEDED_SCRIPT_ROWS = [
    ("amazon", "Amazon"), ("apple", "Apple"), ("google", "Google"),
    ("microsoft", "Microsoft"), ("tiktok", "TikTok"),
]


def _seed_script_company(db_conn, company_id: str, display_name: str) -> None:
    """One published ``ats='script'`` row, exactly as prod holds it.

    ``board_token`` is the company id — that is what the two seed migrations and
    ``companies_seed`` write, and it is precisely why the token-based dedupe cannot
    help here: nothing in a careers URL spells it.
    """
    _seed_public_company(db_conn, company_id, ats="script", board_token=company_id,
                         display_name=display_name)


@pytest.mark.parametrize("url,company_id,display_name", _SCRIPT_BOARD_URLS)
def test_a_script_boards_careers_url_links_instead_of_discovering(
    client, db_conn, monkeypatch, url, company_id, display_name
):
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, company_id, display_name)
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "already_public"
    assert body["companyId"] == company_id
    assert body["displayName"] == display_name
    assert body["finalUrl"] == url
    # The copy names the BOARD, never the company's job set — we matched a host.
    assert "the same job board" in body["detail"]
    assert display_name in body["detail"]

    # NOTHING WAS ENQUEUED. This is the assertion the whole unit exists for: the
    # discovery task is the Claude call and the Chromium session, and a board we
    # already publish must not cost either.
    assert calls == []

    # And NOTHING WAS CREATED — row counts, not response shape.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "user_companies") == 0
    assert _count(db_conn, "company_scripts") == 0
    assert _count(db_conn, "job_listings") == 0
    assert _count(db_conn, "companies", "WHERE id = %s", (company_id,)) == 1

    # The audit stays complete and points at the public company it resolved to.
    assert _count(
        db_conn, "company_add_attempts",
        "WHERE outcome = 'already_public' AND company_id = %s AND resolved_ats = 'script'",
        (company_id,),
    ) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.jobs/en/search",       # with www.
        "https://amazon.jobs/en/search",           # without
        "https://WWW.Amazon.Jobs/EN/Search/",      # mixed case + trailing slash
        "https://www.amazon.jobs/en/search?base_query=engineer&offset=20",  # query
        "https://amazon.jobs./en/search",          # trailing root dot
        "https://amazon.jobs:443/en/search",       # explicit port
        "https://evil.tld@www.amazon.jobs/en/search",  # userinfo before the real host
    ],
)
def test_every_spelling_of_a_script_board_reaches_the_same_answer(
    client, db_conn, monkeypatch, url
):
    """One board, seven URLs. Each is a string a real person or redirect produces."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, "amazon", "Amazon")
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "amazon"
    assert calls == []
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0


def test_the_submitted_url_is_matched_even_when_the_resolver_moved_on(
    client, db_conn, monkeypatch
):
    """``careers.tiktok.com`` 302s to ``lifeattiktok.com`` — but a resolver that lost
    the redirect (or reported a different final URL) must not lose the answer.

    Both URLs are checked precisely because they differ, and they differ in both
    directions: the redirect alias only exists on the submitted side, while a company
    page that redirects INTO one of these boards only exists on the final side.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, "tiktok", "TikTok")
    _patch_no_ats(monkeypatch, final_url="https://some-cdn.example/shell")
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": "https://careers.tiktok.com/"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "tiktok"
    assert calls == []


def test_the_final_url_is_matched_even_when_the_submitted_one_misses(
    client, db_conn, monkeypatch
):
    """A company page that redirects into one of the five is only recognisable there."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, "amazon", "Amazon")
    _patch_no_ats(monkeypatch, final_url="https://www.amazon.jobs/en/search")
    calls = _capture_defer(monkeypatch)

    resp = client.post(
        "/api/users/companies", json={"url": "https://hiring.example/amazon"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "amazon"
    assert calls == []


def test_an_unrelated_host_still_goes_to_discovery(client, db_conn, monkeypatch):
    """The negative control. Discovery is the right answer for almost every URL, and
    this change must not have narrowed it."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    for company_id, display_name in _SEEDED_SCRIPT_ROWS:
        _seed_script_company(db_conn, company_id, display_name)
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


@pytest.mark.parametrize(
    "url",
    [
        # THE near-miss class, and the reason the match is exact-host rather than
        # registrable-domain: every one of these shares a registrable domain with a
        # board above and none of them is that board. Answering "we already track
        # Microsoft" for learn.microsoft.com would be a confidently wrong link.
        "https://learn.microsoft.com/en-us/training/",
        "https://www.microsoft.com/en-us/microsoft-365",
        "https://microsoft.com/",
        "https://aws.amazon.com/careers/",
        "https://www.apple.com/careers/",
        # Google settles it: the registrable domain is a search engine, and only
        # /about/careers under it is a board.
        "https://www.google.com/maps",
        "https://www.google.com/about/careersomething",
    ],
)
def test_a_near_miss_host_is_not_the_board_and_still_goes_to_discovery(
    client, db_conn, monkeypatch, url
):
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    for company_id, display_name in _SEEDED_SCRIPT_ROWS:
        _seed_script_company(db_conn, company_id, display_name)
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


@pytest.mark.parametrize(
    "url",
    [
        # The near-miss class the subdomain cases above do NOT cover: each host ENDS
        # WITH a declared board host without being it, because the shared text stops
        # mid-label. ``notamazon.jobs`` is registrable by anyone.
        "https://notamazon.jobs/en/search",
        "https://evil-careers.microsoft.com/global/en/search",
        "https://myjobs.apple.com/en-us/search",
        "https://fakelifeattiktok.com/search",
    ],
)
def test_a_host_that_merely_ends_with_a_board_host_still_goes_to_discovery(
    client, db_conn, monkeypatch, url
):
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    for company_id, display_name in _SEEDED_SCRIPT_ROWS:
        _seed_script_company(db_conn, company_id, display_name)
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_a_non_public_row_carrying_a_script_id_is_not_offered_as_the_answer(
    client, db_conn, monkeypatch
):
    """``visibility = 'public'`` is a rail, not decoration — pinned directly.

    Today nothing can reach this state through the product: ``new_custom_company_id``
    only ever mints ``u-<base36>``, so a private row cannot carry the id ``amazon``.
    That is exactly why the clause needs its own test rather than an incidental one —
    without this, dropping ``visibility = 'public'`` from the SELECT passes the whole
    suite, and the day an unpublish or import path can produce such a row, the endpoint
    would start answering with a board it no longer publishes.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES ('amazon', 'Amazon', 'script', 'amazon', TRUE, 'user')"
        ).format(sql.Identifier("companies"))
    )
    db_conn.commit()
    url = "https://www.amazon.jobs/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_track_anyway_still_creates_the_private_copy_of_a_script_board(
    client, db_conn, monkeypatch
):
    """Some people legitimately want their own copy, and the escape hatch is the whole
    reason this answer is allowed to be a 200 instead of a refusal."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, "amazon", "Amazon")
    url = "https://www.amazon.jobs/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post(
        "/api/users/companies", json={"url": url, "trackAnyway": True}
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "discovery_pending"
    assert len(calls) == 1
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    # ...and the public Amazon row is untouched.
    assert _count(db_conn, "companies", "WHERE id = 'amazon'") == 1


def test_a_re_add_after_track_anyway_still_resolves_to_the_users_own_row(
    client, db_conn, monkeypatch
):
    """The ordering rule unit 9 established, applied to the host match.

    Somebody who opted into a private copy owns a real row; a plain re-add of that URL
    must keep resolving to THEIR row, or the endpoint stops being idempotent for
    exactly the users who opted in.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, "amazon", "Amazon")
    url = "https://www.amazon.jobs/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    _capture_defer(monkeypatch)

    optin = client.post("/api/users/companies", json={"url": url, "trackAnyway": True})
    assert optin.status_code == 202, optin.text
    company_id = optin.json()["id"]

    again = client.post("/api/users/companies", json={"url": url})

    # 202, because the opted-in row is still ``discovering`` — the re-add answer mirrors
    # the board's state. What this test is about is the id: it resolves to THEIR row.
    assert again.status_code == 202, again.text
    assert again.json()["id"] == company_id
    assert again.json().get("status") != "already_public"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1


# --- The idempotent re-add's audit row must be TERMINAL ------------------------
#
# One add writes TWO audit rows — ``discovery_pending`` from the request, then a
# terminal row from the worker — and the admin dashboard collapses an attempt to its
# newest row, calling a ``discovery_pending`` row older than 40 minutes STUCK. The
# short-circuit branch runs no worker, so a flat ``discovery_pending`` here was half an
# attempt that nothing would ever finish: re-pasting the URL of a board that had been
# tracked and Live for twelve hours made the dashboard report it as stuck.


def _latest_attempt(db_conn) -> dict:
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT outcome, resolved_ats, error_detail, company_id FROM {} "
            "ORDER BY id DESC LIMIT 1"
        ).format(sql.Identifier("company_add_attempts"))
    )
    return dict(cur.fetchone())


def _set_health(db_conn, company_id: str, health: str) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET health_state = %s WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (health, company_id),
    )
    db_conn.commit()


def _set_display_name(db_conn, company_id: str, name: str) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET display_name = %s WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (name, company_id),
    )
    db_conn.commit()


def _set_enabled(db_conn, company_id: str, enabled: bool) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET enabled = %s, next_run_at = NULL WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (enabled, company_id),
    )
    db_conn.commit()


def _add_then_readd(
    client, db_conn, monkeypatch, *, health: str, expect_status: int = 200
) -> tuple[dict, dict]:
    """One real discovery add, forced into ``health``, then the SAME URL re-pasted.

    Returns ``(response body, newest audit row)``. The BODY is half the contract and
    used not to be checked at all: every re-add answered 200 with the tracked-company
    shape, which the frontend renders as "Now tracking …".
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    _capture_defer(monkeypatch)

    first = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert first.status_code == 202, first.text
    company_id = first.json()["id"]
    _set_health(db_conn, company_id, health)

    again = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert again.status_code == expect_status, again.text
    body = again.json()
    if expect_status != 422:
        assert body["id"] == company_id
    return body, _latest_attempt(db_conn)


def test_re_adding_a_tracked_board_writes_a_terminal_added_attempt(
    client, db_conn, monkeypatch
):
    """THE BUG. The board finished discovery hours ago and is tracked; a re-add must
    not open a second pending row that nothing will ever close."""
    body, attempt = _add_then_readd(client, db_conn, monkeypatch, health="unverified")

    assert attempt["outcome"] == "added"
    assert attempt["error_detail"] is None
    # NOT 'discovered': that value is how the monthly quota tells a worker-written row
    # from a request-written one, so reusing it here would stop charging the re-add.
    assert attempt["resolved_ats"] == "already_tracked"
    # A tracked board is the ONE case that legitimately gets the company body — the
    # only shape the frontend renders as "Now tracking …".
    assert body["healthState"] == "unverified"
    assert "status" not in body


def test_re_adding_a_refused_board_retries_its_discovery(
    client, db_conn, monkeypatch
):
    """THE BUG THE OWNER HIT. ``health_state='refused'`` records what our capture
    pipeline could do on the day it ran, not a property of the board — he pasted a
    Y-Combinator-hosted URL before the ``http_html`` transport existed, and re-pasted it
    after. The re-add short-circuited on the refused row, re-ran nothing, and answered
    200 with the company body, which renders as the green "Now tracking …" card over a
    row that is disabled, recipe-less and empty. Re-pasting the URL is the only retry
    the UI offers, so it has to actually retry."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    first = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    company_id = first.json()["id"]
    _set_health(db_conn, company_id, "refused")
    # A refusal disables the row; the retry must leave it disabled until it succeeds.
    _set_enabled(db_conn, company_id, False)
    # The label the REFUSING deployment stored. The owner's row is literally named
    # "Ycombinator" for a board belonging to Raindrop, and there is no rename endpoint,
    # so the retry is the one moment we can correct it.
    _set_display_name(db_conn, company_id, "Stale Name")

    again = client.post("/api/users/companies", json={"url": _NON_ATS_URL})

    # NOT 200, and not the company body: the board is not tracked.
    assert again.status_code == 202, again.text
    assert again.json()["status"] == "discovery_pending"
    assert again.json()["id"] == company_id

    # A SECOND discovery really was enqueued — the whole point.
    assert len(calls) == 2
    assert calls[1]["normalized_url"] == _NON_ATS_URL

    # The row is back to 'discovering' with a fresh checklist, and still disabled and
    # script-less: a retry must scrape nothing until it has proved it can read the board.
    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute(
        "SELECT health_state, enabled, next_run_at, display_name, provider_config "
        "FROM companies WHERE id = %s", (company_id,),
    )
    row = cur.fetchone()
    assert row["health_state"] == "discovering"
    assert row["enabled"] is False
    assert row["next_run_at"] is None
    assert row["provider_config"]["discovery"]["outcome"] == "running"
    assert _count(db_conn, "company_scripts") == 0
    # The label is re-derived. The stored one was written by the deployment that
    # refused the board, and the retry is the only moment we can correct it.
    assert row["display_name"] == "Acme"

    # It is charged like a first add: a counted ``discovery_pending`` audit row.
    attempt = _latest_attempt(db_conn)
    assert attempt["outcome"] == "discovery_pending"
    assert attempt["resolved_ats"] == "discovered"
    assert attempt["company_id"] == company_id


def test_re_adding_a_board_still_discovering_stays_pending(
    client, db_conn, monkeypatch
):
    """THE ONE CASE THAT MUST NOT CHANGE. A run really is in flight, and it really will
    write the terminal half that pairs with this row — so ``pending`` is the truth."""
    body, attempt = _add_then_readd(
        client, db_conn, monkeypatch, health="discovering", expect_status=202,
    )

    assert attempt["outcome"] == "discovery_pending"
    assert attempt["resolved_ats"] == "discovered"
    assert attempt["error_detail"] is None
    # And the RESPONSE says the same thing. It used to hand back the company body for a
    # board whose setup had not finished, which renders as "Now tracking …".
    assert body["status"] == "discovery_pending"


def test_a_retry_that_loses_the_race_resets_nothing(client, db_conn, monkeypatch):
    """The ``health_state = 'refused'`` predicate INSIDE the reset's UPDATE, not just in
    the read above it. Two re-adds arriving together both read a refused row; without
    the predicate both reset it and both enqueue a browser session for the same board.
    The read is faked here because that is the only way to hold the two statements apart
    in one process — what is under test is that the WRITE re-checks."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    _capture_defer(monkeypatch)

    first = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    company_id = first.json()["id"]
    # The row is 'discovering' — the winner of the race already reset it — but our
    # reader still holds the 'refused' snapshot it read a moment ago.
    stale = dict(svc.find_owned_company_by_source_key(
        db_conn, _user_id(db_conn, "a@example.com"),
        svc.discovered_source_key(_NON_ATS_URL),
    ))
    stale["health_state"] = "refused"
    monkeypatch.setattr(
        svc, "find_owned_company_by_source_key", lambda *a, **k: dict(stale)
    )

    assert svc.restart_refused_discovery(
        db_conn, user_id=_user_id(db_conn, "a@example.com"),
        submitted_url=_NON_ATS_URL,
        normalized_url=_NON_ATS_URL, display_name="Acme",
    ) is None

    db_conn.rollback()
    cur = db_conn.cursor()
    cur.execute("SELECT health_state FROM companies WHERE id = %s", (company_id,))
    assert cur.fetchone()["health_state"] == "discovering"


def test_re_adding_a_board_still_discovering_starts_no_second_run(
    client, db_conn, monkeypatch
):
    """The retry above is for REFUSED boards only. A run already in flight is answered,
    not duplicated — a second browser session for the same board is pure spend."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    client.post("/api/users/companies", json={"url": _NON_ATS_URL})

    assert len(calls) == 1


def test_every_re_add_still_spends_a_quota_slot(client, db_conn, monkeypatch):
    """The cap counts URLs ENTERED, not boards created. A re-add creates nothing and
    must still cost one — the regression the ``already_tracked`` marker exists to
    prevent, because ``resolved_ats='discovered'`` on a terminal row reads as the
    worker's own row and is excluded from the count."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    _capture_defer(monkeypatch)

    first = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert first.status_code == 202, first.text
    used_after_add = _quota(client)["used"]
    _set_health(db_conn, first.json()["id"], "unverified")

    assert client.post(
        "/api/users/companies", json={"url": _NON_ATS_URL}
    ).status_code == 200
    assert _quota(client)["used"] == used_after_add + 1


def test_a_script_board_links_even_with_discovery_switched_off(
    client, db_conn, monkeypatch
):
    """The answer does not depend on the discovery flag, and must not.

    With the flag off the alternative is a 422 that reads "No supported ATS board was
    found behind this URL" — about a board on our own front page. "We already publish
    this" is true either way, and it is the more useful sentence.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, "microsoft", "Microsoft")
    url = "https://jobs.careers.microsoft.com/global/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "microsoft"
    assert calls == []
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0


def test_a_disabled_script_company_is_not_offered_as_the_answer(
    client, db_conn, monkeypatch
):
    """Same rail unit 9 has: a disabled public row is a board we have STOPPED reading,
    and a chart that no longer updates is worse than the user's own copy."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "amazon", ats="script", board_token="amazon",
                         display_name="Amazon", enabled=False)
    url = "https://www.amazon.jobs/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_a_script_board_we_do_not_publish_is_not_claimed(client, db_conn, monkeypatch):
    """The table maps a host to an id; the DATABASE decides whether we publish it.

    With no ``amazon`` row seeded there is nothing to link to, so the URL takes the
    ordinary path rather than 200-ing at a company that does not exist.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    url = "https://www.amazon.jobs/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1


def test_another_users_private_copy_is_never_offered_as_the_answer(
    client, db_conn, monkeypatch
):
    """``visibility = 'public'`` is part of the match for the same reason it is in unit
    9's: without it, one user's private board leaks by name to another."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    url = "https://www.amazon.jobs/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    _login(client, "auth0|A", "a@example.com")
    assert client.post(
        "/api/users/companies", json={"url": url, "trackAnyway": True}
    ).status_code == 202

    _login(client, "auth0|B", "b@example.com")
    resp = client.post("/api/users/companies", json={"url": url})

    # No public amazon row exists, so B gets their own discovery — not a pointer at A's.
    assert resp.status_code == 202, resp.text
    assert len(calls) == 2
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 2


# ═══════════════════════════════════════════════════════════════════════════════
# THE COMPANY-NAME MATCH — the third dedupe rung (the ``lifeatspotify.com`` case)
# ═══════════════════════════════════════════════════════════════════════════════
#
# The pure rule is exhaustively tested in ``test_company_name_match.py``. What is
# under test HERE is the thing the owner actually asked for: that it runs BEFORE
# the expensive stuff. Every case below captures ``_defer_discovery`` and asserts
# on the captured list, because "no discovery was enqueued" is the whole unit.

_SPOTIFY_URL = "https://www.lifeatspotify.com/jobs"


def test_a_vanity_careers_domain_names_its_company_before_any_discovery(
    client, db_conn, monkeypatch
):
    """THE case. ``lifeatspotify.com`` is not an ATS board and not a declared careers
    host, so it used to spend a headless Chromium session and a Claude call before the
    job-title overlap could say "this looks like Spotify". The string was in the domain.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "already_public"
    assert body["companyId"] == "spotify"
    assert body["displayName"] == "Spotify"
    assert body["finalUrl"] == _SPOTIFY_URL

    # NOTHING WAS ENQUEUED. This assertion is the unit.
    assert calls == []

    # And NOTHING WAS CREATED — row counts, not response shape.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "user_companies") == 0
    assert _count(db_conn, "company_scripts") == 0
    assert _count(db_conn, "job_listings") == 0

    # The audit says WHICH rung answered, so a false positive is reviewable.
    assert _count(
        db_conn, "company_add_attempts",
        "WHERE outcome = 'already_public' AND company_id = 'spotify' "
        "AND resolved_ats = 'name_guess'",
    ) == 1


def test_the_name_match_hedges_its_copy_and_says_it_guessed(client, db_conn, monkeypatch):
    """A name guess and a board match must NOT read identically.

    A board match names the board and is terminal. This one matched a string in a
    domain, so it says so — and ``matchKind`` is what lets the UI keep a way out here
    while offering none on the two exact rungs.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    _capture_defer(monkeypatch)

    body = client.post("/api/users/companies", json={"url": _SPOTIFY_URL}).json()

    assert body["matchKind"] == "name"
    detail = body["detail"]
    assert "looks like" in detail
    assert "Spotify" in detail
    # It must NOT claim the board, which is the exact rungs' sentence.
    assert "the same job board" not in detail


def test_a_board_match_still_says_board_and_keeps_its_copy(client, db_conn, monkeypatch):
    """The regression rail on the other side: adding the third rung must not have
    softened the two certain ones. Same body, same sentence, ``matchKind='board'``."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_script_company(db_conn, "microsoft", "Microsoft")
    url = "https://jobs.careers.microsoft.com/global/en/search"
    _patch_no_ats(monkeypatch, final_url=url)
    _capture_defer(monkeypatch)

    body = client.post("/api/users/companies", json={"url": url}).json()

    assert body["matchKind"] == "board"
    assert "the same job board" in body["detail"]
    assert "looks like" not in body["detail"]


def test_the_submitted_url_is_matched_by_name_even_when_the_resolver_moved_on(
    client, db_conn, monkeypatch
):
    """A vanity careers host that lands on a bare CDN shell only carries the name in
    what the USER typed."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url="https://some-cdn.example/shell")
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "spotify"
    assert calls == []


def test_the_final_url_is_matched_by_name_when_the_submitted_one_misses(
    client, db_conn, monkeypatch
):
    """And the other direction: a link-shortener or aggregator URL only carries the
    name after the redirect is followed."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    calls = _capture_defer(monkeypatch)

    resp = client.post(
        "/api/users/companies", json={"url": "https://hiring.example/r/8f21c"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "spotify"
    assert calls == []


def test_a_cisco_vanity_url_names_the_published_cisco(client, db_conn, monkeypatch):
    """The owner's other example: "all those URLs are gonna have like Cisco in them"."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "cisco", ats="workday", board_token="cisco",
                         display_name="Cisco")
    url = "https://jobs.cisco.com/jobs/SearchJobs/"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "cisco"
    assert resp.json()["matchKind"] == "name"
    assert calls == []
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0


def test_dropbox_is_never_answered_as_box(client, db_conn, monkeypatch):
    """The collision the whole rule is shaped around. ``dropbox.com`` contains ``box``;
    a naive substring match tells a Dropbox user we already track their company.

    Pinned in BOTH directions: with Box published and Dropbox not, ``dropbox.com``
    must still reach discovery rather than answer "Box".
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "box", ats="greenhouse", board_token="box",
                         display_name="Box")
    url = "https://www.dropbox.com/jobs"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, (
        "dropbox.com must not be answered as Box — a false hit sends somebody to the "
        f"wrong company's chart. got: {resp.text}"
    )
    assert len(calls) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_figma_is_never_answered_as_general_motors(client, db_conn, monkeypatch):
    """The same class, but real: ``gm`` IS a substring of ``figma`` in the published
    table today. Longest-match alone would save this; the affix rule never generates
    the reading at all."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "gm", ats="workday", board_token="gm",
                         display_name="General Motors")
    url = "https://www.figma.com/careers"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/spotify",
        "https://job-boards.greenhouse.io/spotify",
        "https://jobs.lever.co/spotify",
        "https://jobs.ashbyhq.com/spotify",
        "https://spotify.wd1.myworkdayjobs.com/en-US/careers",
        "https://jobs.gem.com/spotify",
        "https://www.linkedin.com/company/spotify/jobs/",
    ],
)
def test_an_ats_host_never_name_matches(client, db_conn, monkeypatch, url):
    """``jobs.lever.co`` reduces to the label ``lever``. If this rung spoke about ATS
    hosts, every Lever board in the world would match a company called Lever the day we
    published one — and every board token in the path is somebody else's company."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _seed_public_company(db_conn, "lever", ats="greenhouse", board_token="lever",
                         display_name="Lever")
    _seed_public_company(db_conn, "gem", ats="gem", board_token="gem", display_name="Gem")
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, (
        f"{url} must reach discovery, not be claimed by name: {resp.text}"
    )
    assert len(calls) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_an_unrelated_domain_still_goes_to_discovery_past_the_name_match(
    client, db_conn, monkeypatch
):
    """The negative control. Discovery is the right answer for almost every URL, and
    this rung must not have narrowed it."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    for company_id, display_name in (
        ("spotify", "Spotify"), ("cursor", "Cursor"), ("block", "Block"),
        ("light", "Light"), ("snap", "Snap"), ("gm", "General Motors"),
    ):
        _seed_public_company(db_conn, company_id, board_token=company_id,
                             display_name=display_name)
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_track_anyway_still_creates_the_private_copy_after_a_name_match(
    client, db_conn, monkeypatch
):
    """The escape hatch, and the reason this rung is allowed to be a guess at all.

    Somebody whose company merely SHARES a string with ours must not be hard-blocked.
    ``trackAnyway`` skips the check and routes to the ordinary discovery path.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    calls = _capture_defer(monkeypatch)

    resp = client.post(
        "/api/users/companies", json={"url": _SPOTIFY_URL, "trackAnyway": True}
    )

    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "discovery_pending"
    assert len(calls) == 1
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_a_re_add_after_track_anyway_resolves_to_the_users_own_row_by_name(
    client, db_conn, monkeypatch
):
    """The ``owned is None`` guard, on the third rung. Someone who pressed the escape
    hatch once owns a real private row, and a re-add of that URL must keep resolving to
    THEIR row rather than being sent back to the public page."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    _capture_defer(monkeypatch)

    optin = client.post(
        "/api/users/companies", json={"url": _SPOTIFY_URL, "trackAnyway": True}
    )
    assert optin.status_code == 202, optin.text
    owned_id = optin.json()["id"]

    again = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    # 202, because the opted-in row is still ``discovering``. The point of this test is
    # the id: it resolves to THEIR row instead of being sent back to the public page.
    assert again.status_code == 202, again.text
    assert again.json().get("status") != "already_public"
    assert again.json()["id"] == owned_id


def test_a_disabled_public_company_is_not_offered_by_name(client, db_conn, monkeypatch):
    """Same rail both other rungs have: a disabled public row is a board we have
    STOPPED reading, and a chart that no longer updates is worse than the user's own
    copy."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify", enabled=False)
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1


def test_another_users_private_row_is_never_offered_by_name(client, db_conn, monkeypatch):
    """``visibility = 'public'`` is part of the match here for the reason it is in both
    other rungs: without it, one user's private board leaks by NAME to another."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    calls = _capture_defer(monkeypatch)

    _login(client, "auth0|A", "a@example.com")
    assert client.post(
        "/api/users/companies", json={"url": _SPOTIFY_URL}
    ).status_code == 202

    _login(client, "auth0|B", "b@example.com")
    resp = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 2
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 2


def test_a_settled_private_row_named_after_the_domain_still_does_not_leak(
    client, db_conn, monkeypatch
):
    """The same leak, but with the row in the state that actually reaches the index.

    A provisional ``discovering`` placeholder is ``enabled = false``, so the ``enabled``
    predicate alone hides it and the ``visibility`` predicate looks redundant. It is not:
    once discovery settles the row to ``tracking`` it is ENABLED, and its auto-derived
    display name is the domain label it came from (``Lifeatspotify``) — an exact name
    key. Without ``visibility = 'public'`` that row answers the next user's add.
    """
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, provider_config, "
            "enabled, visibility) VALUES (%s, %s, %s, %s, '{{}}'::jsonb, true, 'user')"
        ).format(sql.Identifier("companies")),
        ("u-someoneelses", "Lifeatspotify", "discovered", "u-someoneelses"),
    )
    db_conn.commit()

    _login(client, "auth0|B", "b@example.com")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    assert resp.status_code == 202, (
        "another user's PRIVATE discovered board must never be offered as the public "
        f"answer to this add: {resp.text}"
    )
    assert len(calls) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'already_public'") == 0


def test_a_name_match_answers_even_with_discovery_switched_off(
    client, db_conn, monkeypatch
):
    """The answer does not depend on the discovery flag, and must not — same reasoning
    the careers-host rung already carries. With the flag off the alternative is a 422
    reading "No supported ATS board was found behind this URL", about a company on our
    own front page."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    assert resp.status_code == 200, resp.text
    assert resp.json()["companyId"] == "spotify"
    assert calls == []
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0


def test_the_name_match_never_overrules_the_exact_careers_host_table(
    client, db_conn, monkeypatch
):
    """``learn.microsoft.com`` is a training site, and the careers-host table refuses it
    on purpose. The five companies with a declared host table are excluded from the name
    index so a guess can never overturn an exact ``None``."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    for company_id, display_name in _SEEDED_SCRIPT_ROWS:
        _seed_script_company(db_conn, company_id, display_name)
    url = "https://learn.microsoft.com/en-us/training/"
    _patch_no_ats(monkeypatch, final_url=url)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": url})

    assert resp.status_code == 202, resp.text
    assert len(calls) == 1


def test_the_name_match_costs_no_outbound_request(client, db_conn, monkeypatch):
    """Zero network, zero LLM, zero browser — it is pure string work against rows we
    already hold. The probe is the only outbound hop on this endpoint and it lives on
    the other branch; a 404-everything transport makes any regression loud."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _seed_public_company(db_conn, "spotify", ats="lever", board_token="spotify",
                         display_name="Spotify")
    _patch_no_ats(monkeypatch, final_url=_SPOTIFY_URL)
    _capture_defer(monkeypatch)
    requested = _install_recording_transport(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _SPOTIFY_URL})

    assert resp.status_code == 200, resp.text
    assert requested == [], f"the name match must cost no request; got {requested}"


# ==============================================================================
# Per-user add limits — the burst limiter (10/60s) and the monthly cap (20/month)
# ==============================================================================
#
# THE ONE THAT MATTERS is server-side enforcement. Every test below POSTs straight
# at ``/api/users/companies`` with a bearer token and no frontend involved — which is
# exactly the shape of a token copied out of DevTools and replayed with curl. A
# disabled submit button is not a control, and none of these assertions could be
# satisfied by one.


def _install_greenhouse_any(monkeypatch, job_ids: list[int] | None = None) -> None:
    """Like ``_install_greenhouse`` but answers for ANY board token.

    The quota tests need N DISTINCT boards — a re-add of the SAME board takes the
    idempotent branch, which is a different thing — and each distinct token is a
    different probe URL.
    """
    ids = [1, 2, 3] if job_ids is None else job_ids

    def handler(request: httpx.Request) -> httpx.Response:
        if "boards-api.greenhouse.io/v1/boards/" in str(request.url):
            return httpx.Response(200, json={"jobs": [_raw_job(i) for i in ids]})
        return httpx.Response(404)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.user_companies._http_client", factory)


def _seed_attempts(
    db_conn,
    user_id: str,
    n: int,
    *,
    created_at: str = "now()",
    outcome: str = "added",
    resolved_ats: str | None = "greenhouse",
) -> None:
    """Append ``n`` raw ``company_add_attempts`` rows, timestamped as asked.

    Writing the audit rows directly (rather than driving ``n`` real adds) is what
    makes the boundary and rollover cases possible at all: ``created_at`` is a server
    default, so saying so is the only way to place a row in a previous month.
    """
    cur = db_conn.cursor()
    for i in range(n):
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (user_id, submitted_url, outcome, resolved_ats, "
                "created_at) VALUES (%s, %s, %s, %s, " + created_at + ")"
            ).format(sql.Identifier("company_add_attempts")),
            (user_id, f"https://seeded.example/{outcome}/{i}", outcome, resolved_ats),
        )
    db_conn.commit()


def _quota(client) -> dict:
    """The counter exactly as the Add Companies page reads it."""
    body = client.get("/api/users/companies").json()
    return body["quota"]


# --- The cap: 20 URLs per user per calendar month ------------------------------


def test_the_twentieth_add_succeeds_and_the_twenty_first_is_refused(
    client, db_conn, monkeypatch
):
    """The headline rule, at the real default, driven entirely through the endpoint."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|CAP", "cap@example.com")
    _install_greenhouse_any(monkeypatch)

    codes = [
        client.post(
            "/api/users/companies", json={"url": f"https://boards.greenhouse.io/cap{i}"}
        ).status_code
        for i in range(20)
    ]
    assert codes == [201] * 20, codes

    twenty_first = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/cap20"}
    )
    assert twenty_first.status_code == 422, twenty_first.text
    assert twenty_first.json()["reason"] == "monthly_limit_reached"


def test_the_cap_is_enforced_against_a_replayed_token_not_just_the_ui(
    client, db_conn, monkeypatch
):
    """THE TEST THAT MATTERS. No component, no button, no ``disabled`` prop — a bearer
    token aimed straight at the endpoint, which is what a token copied out of DevTools
    and replayed with curl is. Nothing here can be satisfied by frontend state."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 3)
    _login(client, "auth0|REPLAY", "replay@example.com")
    user_id = _user_id(db_conn, "replay@example.com")
    _seed_attempts(db_conn, user_id, 3)
    _install_greenhouse_any(monkeypatch)

    before_companies = _count(db_conn, "companies", "WHERE visibility = 'user'")

    for _ in range(5):
        resp = client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/replay"}
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["reason"] == "monthly_limit_reached"

    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == before_companies


def test_the_cap_refuses_before_spending_anything(client, db_conn, monkeypatch):
    """Zero outbound HTTP, no company, no ownership row, and discovery never enqueued.

    A cap that refuses AFTER the resolver has run has already spent the thing it
    exists to protect, so this pins the check's POSITION in the handler rather than
    merely its existence.
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1)
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|NOSPEND", "nospend@example.com")
    user_id = _user_id(db_conn, "nospend@example.com")
    _seed_attempts(db_conn, user_id, 1)
    requested = _install_recording_transport(monkeypatch)
    deferred = _capture_defer(monkeypatch)

    before_companies = _count(db_conn, "companies", "WHERE visibility = 'user'")
    before_owned = _count(db_conn, "user_companies", "WHERE user_id = %s", (user_id,))

    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/nospend"}
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "monthly_limit_reached"
    assert requested == [], f"a refused add must make no outbound request; got {requested}"
    assert deferred == [], "a refused add must never enqueue discovery"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == before_companies
    assert _count(db_conn, "user_companies", "WHERE user_id = %s", (user_id,)) == before_owned


def test_the_cap_refusal_is_not_itself_recorded_as_an_attempt(
    client, db_conn, monkeypatch
):
    """A DECISION, asserted so it cannot drift: a refusal at the cap writes no audit row.

    It never reached the resolver and created nothing, so it is not an add attempt —
    and recording it would let a replayed token inflate ``used`` without bound, which
    would stop the row count meaning "URLs we acted on".
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 2)
    _login(client, "auth0|NOREC", "norec@example.com")
    user_id = _user_id(db_conn, "norec@example.com")
    _seed_attempts(db_conn, user_id, 2)
    before = _count(db_conn, "company_add_attempts", "WHERE user_id = %s", (user_id,))

    for _ in range(3):
        client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/norecord"}
        )

    assert _count(db_conn, "company_add_attempts", "WHERE user_id = %s", (user_id,)) == before


def test_an_unreadable_count_fails_CLOSED(client, db_conn, monkeypatch):
    """A database error reading the count is a 500, never a pass-through.

    The count IS the control, so "we couldn't read it, carry on" would fail open on
    exactly the request the cap exists to stop.
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|DBFAIL", "dbfail@example.com")
    requested = _install_recording_transport(monkeypatch)

    def _boom(*_args, **_kwargs):
        raise psycopg2.OperationalError("injected failure")

    monkeypatch.setattr(svc, "count_add_attempts_since", _boom)

    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/dbfail"}
    )

    assert resp.status_code == 500, resp.text
    assert requested == [], "a failed quota read must not fall through to the resolver"


def test_every_outcome_spends_a_slot_including_refusals(client, db_conn, monkeypatch):
    """Three FAILED adds exhaust a three-slot month exactly as three successful ones do.

    The owner's rule caps URLs ENTERED, not boards created: "a success, a refusal, a
    board that turns out to be one we already publish — all the same". This is the
    half of it a spend-based rule would have got wrong.
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 3)
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    _login(client, "auth0|FAIL", "fail@example.com")
    _patch_no_ats(monkeypatch)

    for i in range(3):
        resp = client.post("/api/users/companies", json={"url": f"https://no-ats.example/{i}"})
        assert resp.status_code == 422, resp.text
        assert resp.json()["reason"] == "no_ats_detected"

    fourth = client.post("/api/users/companies", json={"url": "https://no-ats.example/3"})
    assert fourth.status_code == 422, fourth.text
    assert fourth.json()["reason"] == "monthly_limit_reached"


def test_an_already_published_board_spends_a_slot(client, db_conn, monkeypatch):
    """Pasting a board we already publish costs us nothing and still counts. Simple
    beats fair here — the owner's call, and it is what keeps the rule to one
    sentence."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1)
    _login(client, "auth0|PUB", "pub@example.com")
    _seed_public_company(db_conn, "pubdupe", ats="greenhouse", board_token="pubdupe",
                         display_name="Pub Dupe")
    _install_greenhouse_any(monkeypatch)

    first = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/pubdupe"}
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "already_public"

    second = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/anything"}
    )
    assert second.status_code == 422, second.text
    assert second.json()["reason"] == "monthly_limit_reached"


def test_deleting_a_company_does_not_refund_a_slot(client, db_conn, monkeypatch):
    """Add, delete, add — still refused. The purge deliberately leaves
    ``company_add_attempts`` behind, which is the whole mechanism behind "no refund"."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1)
    _login(client, "auth0|REFUND", "refund@example.com")
    _install_greenhouse_any(monkeypatch)

    created = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/refund"}
    )
    assert created.status_code == 201, created.text

    deleted = client.delete(f"/api/users/companies/{created.json()['id']}")
    assert deleted.status_code == 204, deleted.text

    again = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/refund2"}
    )
    assert again.status_code == 422, again.text
    assert again.json()["reason"] == "monthly_limit_reached"


def test_checking_a_url_does_not_spend_a_slot(client, db_conn, monkeypatch):
    """``POST /api/companies/resolve`` writes nothing and must not decrement.

    Only "Track this company" and an auto-started discovery count — the two calls that
    create something. Checking is already capped at 10/minute on its own route.
    """
    from api.services.rate_limit import resolve_rate_limiter

    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|CHECK", "check@example.com")
    resolve_rate_limiter.reset()
    monkeypatch.setattr(resolve_rate_limiter, "_max", 1_000)

    def _resolve_client() -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            if "boards-api.greenhouse.io" in str(request.url):
                return httpx.Response(200, json={"jobs": [_raw_job(1)]})
            return httpx.Response(404)

        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.companies._http_client", _resolve_client)

    before = _quota(client)["used"]
    for _ in range(5):
        resp = client.post(
            "/api/companies/resolve", json={"url": "https://boards.greenhouse.io/checkonly"}
        )
        assert resp.status_code == 200, resp.text
    assert _quota(client)["used"] == before

    resolve_rate_limiter.reset()


def test_a_worker_written_discovery_verdict_does_not_spend_a_second_slot(
    client, db_conn, monkeypatch
):
    """ONE submission, TWO audit rows, ONE slot.

    THIS IS WHERE THE APPROVED PLAN'S "straight row count" WAS WRONG. A non-ATS URL
    writes ``discovery_pending`` from the REQUEST, and then — minutes later, from the
    WORKER — ``added`` (``add_discovered_company``) or ``refused``
    (``record_discovery_refusal``). Both carry ``resolved_ats='discovered'``. Counting
    the second would silently halve the cap for every discovered board.
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|WORKER", "worker@example.com")
    user_id = _user_id(db_conn, "worker@example.com")

    _seed_attempts(db_conn, user_id, 1, outcome="discovery_pending", resolved_ats="discovered")
    assert _quota(client)["used"] == 1

    # The worker's two possible verdicts for that SAME submission.
    _seed_attempts(db_conn, user_id, 1, outcome="added", resolved_ats="discovered")
    _seed_attempts(db_conn, user_id, 1, outcome="refused", resolved_ats="discovered")

    assert _quota(client)["used"] == 1, (
        "the worker's terminal row is the same submission reaching its verdict, "
        "not a second URL"
    )


def test_an_ats_add_still_spends_its_slot(client, db_conn, monkeypatch):
    """The mirror of the test above: the exclusion must not swallow a real ATS add,
    whose audit row is ALSO ``outcome='added'`` — only ``resolved_ats`` separates
    them."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|ATSCOUNT", "atscount@example.com")
    user_id = _user_id(db_conn, "atscount@example.com")

    _seed_attempts(db_conn, user_id, 2, outcome="added", resolved_ats="greenhouse")
    assert _quota(client)["used"] == 2


def test_zero_refuses_every_add_including_a_users_first(client, db_conn, monkeypatch):
    """ZERO MEANS ZERO — the half of this that used to mean the exact opposite.

    ``0`` was the unlimited sentinel, so a value that landed on it by accident (a
    typo, a bad deploy template, an empty string coerced to an int) handed every
    signed-in user unbounded browser + LLM spend. It now refuses, and it refuses a
    brand-new user with nothing spent, which is the case that proves there is no
    sentinel left: ``used=0 >= limit=0``.
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 0)
    _login(client, "auth0|ZERO", "zero@example.com")
    _install_greenhouse_any(monkeypatch)
    before = _quota(client)
    assert before["used"] == 0 and before["limit"] == 0, before

    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/zeroed"}
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "monthly_limit_reached", resp.text
    # And the copy does not read "you've used all 0 of your company adds", which is
    # what the plain sentence would say to somebody who has spent nothing.
    detail = resp.json()["detail"]
    assert "all 0" not in detail, detail
    assert "turned off" in detail, detail


def test_a_large_limit_permits_the_add(client, db_conn, monkeypatch):
    """The other half of the swap: local dev buys its freedom with a big number now,
    not with ``0``. Far past any plausible usage, and never refused."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 10_000)
    _login(client, "auth0|BIG", "big@example.com")
    user_id = _user_id(db_conn, "big@example.com")
    _seed_attempts(db_conn, user_id, 500)
    _install_greenhouse_any(monkeypatch)

    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/roomy"}
    )
    assert resp.status_code == 201, resp.text
    assert _quota(client)["limit"] == 10_000


def test_the_monthly_limit_default_is_pinned() -> None:
    """``extra="ignore"`` means a typo'd env var name is silently dropped and this
    default stands. With 20 as the default a typo leaves the cap ON; an
    ``..._ENABLED=false``-shaped flag would fail OPEN on the same typo."""
    fields = type(settings).model_fields
    assert fields["custom_company_monthly_add_limit"].default == 20


def test_zero_is_still_a_legal_value() -> None:
    """``ge=0``, not ``gt=0``. Zero has to stay constructible now that it means
    something: it is the per-user kill switch, one env var that stops every add
    without a deploy. A ``gt=0`` bound would turn that into a boot crash."""
    from pydantic import ValidationError

    assert type(settings)(custom_company_monthly_add_limit=0)
    with pytest.raises(ValidationError):
        type(settings)(custom_company_monthly_add_limit=-1)


def test_booting_with_adds_disabled_logs_a_warning(monkeypatch, caplog) -> None:
    """The warning survived the sentinel's removal, INVERTED. It used to say the gate
    was wide open; it now says nothing can get through. Still worth a boot line
    because ``0`` is reachable by accident and looks like a broken feature."""
    import logging as _logging

    from api.services.add_quota import warn_if_adds_disabled

    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 0)
    caplog.clear()
    with caplog.at_level(_logging.WARNING, logger="api.services.add_quota"):
        warn_if_adds_disabled()
    assert "CUSTOM_COMPANY_MONTHLY_ADD_LIMIT is 0" in caplog.text
    assert "NO user can add a company" in caplog.text

    caplog.clear()
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    with caplog.at_level(_logging.WARNING, logger="api.services.add_quota"):
        warn_if_adds_disabled()
    assert caplog.text == ""


# --- The window: calendar month, UTC -------------------------------------------


def test_last_months_attempts_do_not_count(client, db_conn, monkeypatch):
    """Month rollover. A user at 20 on the 31st is at 0 used one second later."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 3)
    _login(client, "auth0|ROLL", "roll@example.com")
    user_id = _user_id(db_conn, "roll@example.com")
    _seed_attempts(
        db_conn, user_id, 20,
        created_at="date_trunc('month', now() AT TIME ZONE 'UTC') - interval '1 day'",
    )
    _install_greenhouse_any(monkeypatch)

    assert _quota(client)["used"] == 0
    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/newmonth"}
    )
    assert resp.status_code == 201, resp.text


def test_the_first_instant_of_the_month_counts(client, db_conn, monkeypatch):
    """The boundary is INCLUSIVE at the start: a row stamped exactly at midnight UTC
    on the 1st belongs to the new month, not the old one."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1)
    _login(client, "auth0|BOUND", "bound@example.com")
    user_id = _user_id(db_conn, "bound@example.com")
    _seed_attempts(
        db_conn, user_id, 1,
        created_at="date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",
    )
    _install_greenhouse_any(monkeypatch)

    assert _quota(client)["used"] == 1
    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/boundary"}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "monthly_limit_reached"


def test_the_last_instant_of_last_month_does_not_count(client, db_conn, monkeypatch):
    """...and EXCLUSIVE at the other end. One microsecond before the boundary is last
    month's spend, and it is already forgiven."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1)
    _login(client, "auth0|BOUND2", "bound2@example.com")
    user_id = _user_id(db_conn, "bound2@example.com")
    _seed_attempts(
        db_conn, user_id, 1,
        created_at=(
            "(date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') "
            "- interval '1 microsecond'"
        ),
    )
    assert _quota(client)["used"] == 0


def test_the_month_window_is_utc_and_rolls_over_december() -> None:
    """Pure. December rolls to January of the NEXT year, a non-UTC offset is converted
    rather than ignored, and a naive datetime is REFUSED — silently reading it in the
    server's local timezone is exactly how "one instant for everybody" stops holding."""
    from datetime import datetime, timedelta, timezone

    from api.services.add_quota import month_window

    start, nxt = month_window(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert nxt == datetime(2027, 1, 1, tzinfo=timezone.utc)

    # 8pm US Central on the last day of August is already September in UTC.
    central = timezone(timedelta(hours=-5))
    start, _ = month_window(datetime(2026, 8, 31, 20, 0, tzinfo=central))
    assert start == datetime(2026, 9, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        month_window(datetime(2026, 8, 20, 12, 0))


# --- The counter on GET /api/users/companies -----------------------------------


def test_the_list_endpoint_carries_the_counter(client, db_conn, monkeypatch):
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|Q", "q@example.com")
    user_id = _user_id(db_conn, "q@example.com")
    _seed_attempts(db_conn, user_id, 3)

    quota = _quota(client)
    assert quota["used"] == 3
    assert quota["limit"] == 20
    # The reset instant, so the UI never has to compute a month boundary itself.
    assert quota["resetsAt"].endswith("Z") or "+00:00" in quota["resetsAt"]


def test_a_brand_new_user_sees_a_full_allowance(client, monkeypatch):
    """Signed in, no ``users`` row yet. Nothing owned and nothing spent — the counter
    must still render, or a first-time visitor sees a blank where the allowance goes."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|NEVERSEEN", "never-seen@example.com")

    body = client.get("/api/users/companies").json()
    assert body["companies"] == []
    assert body["quota"]["used"] == 0
    assert body["quota"]["limit"] == 20


def test_the_counter_moves_with_each_submission(client, db_conn, monkeypatch):
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|TICK", "tick@example.com")
    _install_greenhouse_any(monkeypatch)

    assert _quota(client)["used"] == 0
    client.post("/api/users/companies", json={"url": "https://boards.greenhouse.io/tick1"})
    assert _quota(client)["used"] == 1
    client.post("/api/users/companies", json={"url": "https://boards.greenhouse.io/tick2"})
    assert _quota(client)["used"] == 2


# --- The burst limiter: 10 per 60s, per user -----------------------------------


def test_the_eleventh_add_in_a_minute_is_refused(client, db_conn, monkeypatch):
    """The limit the owner believed he already had. It was on ``/api/companies/resolve``
    — which spends nothing — and NOT on this route, which starts a browser and an LLM
    call. It looked done because the UI calls resolve first; a replayed token aimed
    straight here bypassed it entirely."""
    # A LARGE number, not 0 — 0 means "no adds at all" now, which would refuse these
    # POSTs for the wrong reason and make the burst assertion meaningless.
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1_000_000)
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 10)
    user_company_add_rate_limiter.reset()
    _login(client, "auth0|BURST", "burst@example.com")
    _install_greenhouse_any(monkeypatch)

    codes = [
        client.post(
            "/api/users/companies",
            json={"url": f"https://boards.greenhouse.io/burst{i}"},
        ).status_code
        for i in range(11)
    ]

    assert codes[:10] == [201] * 10, codes
    assert codes[10] == 429, codes


def test_the_burst_refusal_says_how_long_to_wait_in_the_body(
    client, db_conn, monkeypatch
):
    """``api/users.ts`` forwards through ``forwardResponse``, which copies status +
    body ONLY — the same reason ``X-Next-Cursor`` needs its own explicit line there.
    A ``Retry-After`` header therefore never reaches the browser, so the wait has to be
    in the message. The header is still sent, for direct API callers that do see it."""
    # A LARGE number, not 0 — 0 means "no adds at all" now, which would refuse these
    # POSTs for the wrong reason and make the burst assertion meaningless.
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1_000_000)
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 1)
    user_company_add_rate_limiter.reset()
    _login(client, "auth0|WAIT", "wait@example.com")
    _install_greenhouse_any(monkeypatch)

    client.post("/api/users/companies", json={"url": "https://boards.greenhouse.io/w1"})
    resp = client.post("/api/users/companies", json={"url": "https://boards.greenhouse.io/w2"})

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert "seconds" in detail
    assert any(ch.isdigit() for ch in detail), detail
    assert int(resp.headers["retry-after"]) >= 1


def test_the_burst_limit_is_keyed_per_user(client, db_conn, monkeypatch):
    """One user's burst must not lock everybody else out — the key is the
    authenticated subject, not a global counter."""
    # A LARGE number, not 0 — 0 means "no adds at all" now, which would refuse these
    # POSTs for the wrong reason and make the burst assertion meaningless.
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1_000_000)
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 1)
    user_company_add_rate_limiter.reset()
    _install_greenhouse_any(monkeypatch)

    _login(client, "auth0|KEY1", "key1@example.com")
    client.post("/api/users/companies", json={"url": "https://boards.greenhouse.io/k1"})
    blocked = client.post("/api/users/companies", json={"url": "https://boards.greenhouse.io/k2"})
    assert blocked.status_code == 429

    _login(client, "auth0|KEY2", "key2@example.com")
    other = client.post("/api/users/companies", json={"url": "https://boards.greenhouse.io/k3"})
    assert other.status_code == 201, other.text


def test_the_burst_limit_settings_are_pinned() -> None:
    """Same reasoning as every other setting here: ``extra="ignore"`` hides a typo."""
    fields = type(settings).model_fields
    assert fields["user_company_add_rate_limit_max"].default == 10
    assert fields["user_company_add_rate_limit_window_seconds"].default == 60


# --- Ordering: the feature flag answers first ----------------------------------


def test_neither_limit_is_checked_before_the_feature_flag(client, monkeypatch):
    """With the feature off the route must stay a clean 503 — not a 429, and not a 422
    that reads as a quota problem on a feature that is not even running."""
    monkeypatch.setattr(settings, "custom_company_sources_enabled", False)
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1)
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 1)
    user_company_add_rate_limiter.reset()
    _login(client, "auth0|FLAGOFF", "flagoff@example.com")

    for _ in range(3):
        resp = client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/flagoff"}
        )
        assert resp.status_code == 503, resp.text


# --- The admin exemption: the cap does not apply to an admin --------------------
#
# The cap is a SPEND control, and the person paying for the spend is the one being
# blocked by it while testing. An admin grant is a row in ``admins`` — the same
# concept ``require_admin`` reads — and the exemption is resolved inside
# ``add_quota.get_quota``, the ONE function behind both the refusal and the counter.
# Both directions are asserted below, because a guard on money that silently stops
# applying to everybody is a worse bug than the one being fixed here.


def _make_admin(client, db_conn, sub: str, email: str) -> str:
    """Sign in as ``email`` and give that users row an admin grant. Returns its id."""
    _login(client, sub, email)
    user_id = _user_id(db_conn, email)
    _insert_admin(db_conn, user_id)
    return user_id


def test_an_admin_at_the_cap_is_not_refused(client, db_conn, monkeypatch):
    """THE BUG. An admin sitting on a full month adds anyway, and keeps adding."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 3)
    user_id = _make_admin(client, db_conn, "auth0|ADMINCAP", "admincap@example.com")
    _seed_attempts(db_conn, user_id, 3)
    _install_greenhouse_any(monkeypatch)

    codes = [
        client.post(
            "/api/users/companies", json={"url": f"https://boards.greenhouse.io/ac{i}"}
        ).status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 201], codes


def test_an_admin_is_not_refused_even_at_the_kill_switch(client, db_conn, monkeypatch):
    """``0`` is the per-user kill switch and it is still a cap, so the exemption has to
    cover it too — otherwise the one person who can turn adds back on is the one person
    locked out while they investigate."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 0)
    _make_admin(client, db_conn, "auth0|ADMINZERO", "adminzero@example.com")
    _install_greenhouse_any(monkeypatch)

    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/adminzero"}
    )
    assert resp.status_code == 201, resp.text


def test_an_admins_adds_are_still_recorded(client, db_conn, monkeypatch):
    """EXEMPT FROM REFUSAL, NOT FROM THE AUDIT. ``company_add_attempts`` is what the
    admin dashboard and the audit trail read, and it is also what ``used`` counts — so
    an admin's ``used`` keeps climbing past ``limit``, it is simply never compared
    against it. An exemption that skipped the write would put a hole in the audit and
    make the count stop meaning "URLs we acted on"."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 2)
    user_id = _make_admin(client, db_conn, "auth0|ADMINREC", "adminrec@example.com")
    _seed_attempts(db_conn, user_id, 2)
    _install_greenhouse_any(monkeypatch)
    before = _count(db_conn, "company_add_attempts", "WHERE user_id = %s", (user_id,))

    for i in range(3):
        resp = client.post(
            "/api/users/companies", json={"url": f"https://boards.greenhouse.io/ar{i}"}
        )
        assert resp.status_code == 201, resp.text

    after = _count(db_conn, "company_add_attempts", "WHERE user_id = %s", (user_id,))
    assert after == before + 3, f"{before} -> {after}"


def test_a_non_admin_at_the_cap_is_still_refused_with_the_same_reason(
    client, db_conn, monkeypatch
):
    """The other direction, with an admin PRESENT in the table. The exemption is per
    caller — "somebody is an admin" must not uncap everybody, which is what a lookup
    keyed on the wrong thing (or a global ``EXISTS``) would do."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 2)
    _make_admin(client, db_conn, "auth0|THEADMIN", "theadmin@example.com")

    _login(client, "auth0|PLAIN", "plain@example.com")
    plain_id = _user_id(db_conn, "plain@example.com")
    _seed_attempts(db_conn, plain_id, 2)
    _install_greenhouse_any(monkeypatch)

    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/plain"}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "monthly_limit_reached", resp.text
    assert "all 2 of your company adds" in resp.json()["detail"], resp.text


def test_the_counter_says_the_same_thing_the_server_enforces(
    client, db_conn, monkeypatch
):
    """THE AGREEMENT TEST, and the reason the exemption lives in ``get_quota``.

    An admin who is never refused must not be reading "3 of 20 adds left" — the
    counter and the refusal come from one ``AddQuota``, so "no cap for you" has to be
    what the payload says. It says it by OMITTING the block, which is the frontend's
    existing "no cap in force" case (``addsRemaining`` answers null → no counter, no
    disabled button). A non-admin in the same month still gets real numbers.
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 5)

    admin_id = _make_admin(client, db_conn, "auth0|ADMINQ", "adminq@example.com")
    _seed_attempts(db_conn, admin_id, 5)
    body = client.get("/api/users/companies").json()
    assert body["quota"] is None, (
        f"an exempt caller must carry no counter, got {body['quota']!r}"
    )

    _login(client, "auth0|PLAINQ", "plainq@example.com")
    plain_id = _user_id(db_conn, "plainq@example.com")
    _seed_attempts(db_conn, plain_id, 5)
    quota = client.get("/api/users/companies").json()["quota"]
    assert quota is not None and quota["used"] == 5 and quota["limit"] == 5, quota


def test_an_admin_lookup_failure_fails_CLOSED(client, db_conn, monkeypatch):
    """A DATABASE ERROR MUST NEVER BE AN EXEMPTION.

    The admin lookup is a read, and a read can fail. If it does, the caller is an
    ordinary user and the cap applies — an outage that silently uncapped every add
    would be the same fail-open shape ``0``-means-unlimited used to be, and worse than
    the bug this exemption fixes. The caller below is a REAL admin, and is refused.
    """
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1)
    user_id = _make_admin(client, db_conn, "auth0|ADMINBOOM", "adminboom@example.com")
    _seed_attempts(db_conn, user_id, 1)
    requested = _install_recording_transport(monkeypatch)

    def _boom(*_args, **_kwargs):
        raise psycopg2.OperationalError("injected admin-lookup failure")

    monkeypatch.setattr("api.services.add_quota.is_admin_by_email", _boom)

    resp = client.post(
        "/api/users/companies", json={"url": "https://boards.greenhouse.io/adminboom"}
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "monthly_limit_reached", resp.text
    assert requested == [], "a refused add must still make no outbound request"
    # And the counter agrees with the refusal it just made — the block is present,
    # because as far as these requests could tell the caller was not an admin.
    assert client.get("/api/users/companies").json()["quota"] is not None


def test_an_admin_is_still_subject_to_the_burst_limiter(client, db_conn, monkeypatch):
    """A DECIDED TRADE-OFF, asserted so it cannot drift. The 10/60s limiter is an abuse
    guard, not a budget: an admin hammering this endpoint is still hammering somebody
    else's live job board, and 10 a minute has never been what blocks real work. The
    monthly cap is the money control, and it is the only one the exemption touches."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1_000_000)
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 2)
    user_company_add_rate_limiter.reset()
    _make_admin(client, db_conn, "auth0|ADMINBURST", "adminburst@example.com")
    _install_greenhouse_any(monkeypatch)

    codes = [
        client.post(
            "/api/users/companies", json={"url": f"https://boards.greenhouse.io/ab{i}"}
        ).status_code
        for i in range(3)
    ]
    assert codes[:2] == [201, 201], codes
    assert codes[2] == 429, codes


def test_the_exemption_changes_exhausted_and_nothing_else() -> None:
    """Pure. ``used`` and ``limit`` stay real for an exempt caller — an operator
    reading a log line or the admin dashboard sees the actual numbers, not a hole —
    and only the one question the server asks changes its answer."""
    from datetime import datetime, timezone

    from api.services.add_quota import AddQuota, quota_response

    resets = datetime(2026, 9, 1, tzinfo=timezone.utc)
    capped = AddQuota(used=20, limit=20, resets_at=resets)
    exempt = AddQuota(used=20, limit=20, resets_at=resets, exempt=True)

    assert capped.over_limit and exempt.over_limit
    assert capped.exhausted is True
    assert exempt.exhausted is False
    assert exempt.used == 20 and exempt.limit == 20

    # ...and the counter half, from the same value.
    assert quota_response(exempt) is None
    body = quota_response(capped)
    assert body is not None and body.used == 20 and body.limit == 20


def test_a_caller_with_no_users_row_is_never_exempt(client, monkeypatch) -> None:
    """``admins.user_id`` is a foreign key to ``users.id``, so a caller with no users
    row cannot hold a grant — which is why ``get_quota_for_new_user`` needs no lookup
    to answer "not exempt". Pinned because the counter would otherwise vanish for every
    brand-new visitor if that default ever flipped."""
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 20)
    _login(client, "auth0|NOROW", "no-row-yet@example.com")

    quota = client.get("/api/users/companies").json()["quota"]
    assert quota is not None and quota["used"] == 0 and quota["limit"] == 20, quota
