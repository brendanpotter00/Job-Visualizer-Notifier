"""``PATCH /api/users/companies/{id}`` — the owner renames one of their own boards.

A SEPARATE MODULE from ``test_user_companies_router.py`` on purpose. The rename has one
non-obvious rule that the rest of that file has no reason to care about — a user's name
must survive every path that re-derives a name from the URL — and grouping the proofs of
that rule together is what makes it obvious when one of them is deleted. The fixtures
below are the same shapes that file uses; they are duplicated rather than imported so
this module does not break when an unrelated test's helper is renamed.

The load-bearing cases are :func:`test_a_rename_survives_the_retry_of_a_refused_board`
and :func:`test_a_rename_survives_a_re_discovery`. If either of those ever goes green by
accident — because someone made the endpoint write ``display_name`` — the feature is a
trap: the user renames "Ycombinator" to "Raindrop", re-pastes the URL, and silently gets
"Ycombinator" back.
"""

import httpx
import pytest
from psycopg2 import sql

from api.auth.dependencies import get_current_user
from api.config import settings
from api.services import custom_companies_service as svc
from api.services.rate_limit import (
    user_company_add_rate_limiter,
    user_company_rename_rate_limiter,
)

GREENHOUSE_URL = "https://boards.greenhouse.io/duolingo"
_NON_ATS_URL = "https://acme.example/careers"


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    """The parent flag ON (every test here is about the feature), the discovery
    sub-flag OFF (its production default). Tests about discovery turn it on
    themselves. Pinned rather than inherited because ``Settings`` loads the untracked,
    developer-specific ``.env.local``."""
    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)


@pytest.fixture(autouse=True)
def no_limits(monkeypatch):
    """Neutralise all three limits for every test that is not about them.

    A large number, never ``0``: ``custom_company_monthly_add_limit = 0`` means "no
    adds at all", so it would refuse the POST every test here needs to make first. The
    two sliding-window limiters are process-wide singletons, so they are RESET as well
    as re-sized — resizing alone leaves the previous test's timestamps in the bucket.
    """
    user_company_add_rate_limiter.reset()
    user_company_rename_rate_limiter.reset()
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 1_000_000)
    monkeypatch.setattr(user_company_rename_rate_limiter, "_max", 1_000_000)
    monkeypatch.setattr(settings, "custom_company_monthly_add_limit", 1_000_000)
    yield
    user_company_add_rate_limiter.reset()
    user_company_rename_rate_limiter.reset()


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


def _row(db_conn, company_id: str) -> dict:
    """Both name columns straight from the table — the only way to tell "the rename
    landed" from "the read path happens to be showing the right thing"."""
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT display_name, user_display_name, health_state, enabled "
            "FROM {} WHERE id = %s"
        ).format(sql.Identifier("companies")),
        (company_id,),
    )
    return dict(cur.fetchone())


def _set_health(db_conn, company_id: str, health: str) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET health_state = %s, enabled = FALSE WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (health, company_id),
    )
    db_conn.commit()


def _count(db_conn, table: str, where: str = "", params: tuple = ()) -> int:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT count(*) AS n FROM {} " + where).format(sql.Identifier(table)),
        params,
    )
    return int(cur.fetchone()["n"])


def _add_ats_company(client, monkeypatch) -> str:
    """One tracked ATS board owned by the logged-in caller. Returns its company id."""
    _install_greenhouse(monkeypatch, [1, 2])
    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def _add_discovered_company(client, monkeypatch) -> str:
    """One board on the DISCOVERY path (202 provisional row). Returns its company id."""
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _patch_no_ats(monkeypatch)
    _capture_defer(monkeypatch)
    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert resp.status_code == 202, resp.text
    return str(resp.json()["id"])


# --- The happy path ---------------------------------------------------------


def test_rename_returns_the_new_name_and_persists_it(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": "Raindrop"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["displayName"] == "Raindrop"
    assert body["id"] == company_id
    # The full row shape, not a stub: the frontend replaces a list entry with this.
    assert body["sourceId"] == f"custom:{company_id}"
    assert body["ats"] == "greenhouse"
    assert "openJobCount" in body

    listed = client.get("/api/users/companies").json()["companies"]
    assert [c["displayName"] for c in listed] == ["Raindrop"]


def test_the_rename_lands_in_user_display_name_and_leaves_the_derived_one_alone(
    client, db_conn, monkeypatch
):
    """THE WHOLE DESIGN, asserted directly on the two columns.

    ``display_name`` keeps the label discovery derived; ``user_display_name`` holds the
    one the user chose. If a future change collapses these into one column, this is the
    test that says so — everything else would still pass, because every read path
    resolves the two into one field.
    """
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    derived = _row(db_conn, company_id)["display_name"]
    assert derived  # whatever the add derived; we only care that it survives

    client.patch(f"/api/users/companies/{company_id}", json={"displayName": "Raindrop"})

    row = _row(db_conn, company_id)
    assert row["user_display_name"] == "Raindrop"
    assert row["display_name"] == derived, (
        "the derived name must be preserved, not overwritten — it is what a re-discovery "
        "keeps maintaining and what a future 'reset to suggested name' would restore"
    )


def test_a_second_rename_replaces_the_first(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    client.patch(f"/api/users/companies/{company_id}", json={"displayName": "First"})
    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": "Second"}
    )
    assert resp.status_code == 200
    assert resp.json()["displayName"] == "Second"
    assert _row(db_conn, company_id)["user_display_name"] == "Second"


def test_rename_writes_no_add_attempt_and_spends_no_quota(
    client, db_conn, monkeypatch
):
    """A rename is not a URL we acted on, so it must not touch the monthly spend guard.

    ``company_add_attempts`` is the quota's ONLY input
    (``custom_companies_service._QUOTA_COUNTED_PREDICATE``), so "writes no row there"
    and "costs no slot" are the same assertion — and it is the one that stops fixing a
    typo from costing one of twenty browser sessions.
    """
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    before = _count(db_conn, "company_add_attempts")

    client.patch(f"/api/users/companies/{company_id}", json={"displayName": "Raindrop"})

    assert _count(db_conn, "company_add_attempts") == before


# --- The non-obvious rule: a rename survives re-derivation -------------------


def test_a_rename_survives_the_retry_of_a_refused_board(client, db_conn, monkeypatch):
    """THE TRAP THIS FEATURE WOULD OTHERWISE BE.

    ``restart_refused_discovery`` re-derives the display name on every retry, and
    re-pasting the URL is the ONLY retry the UI offers. Before the rename shipped that
    refresh was the one chance to correct a bad label; after it, refreshing the column
    the USER writes would silently undo their rename. It refreshes the DERIVED column
    instead, so both stay true at once.
    """
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_discovered_company(client, monkeypatch)
    client.patch(f"/api/users/companies/{company_id}", json={"displayName": "Raindrop"})
    # The refusal the user is retrying.
    _set_health(db_conn, company_id, "refused")

    again = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert again.status_code == 202, again.text
    assert again.json()["id"] == company_id
    # The 202 body is the discovery-pending notice (status/detail/finalUrl/id) and
    # carries no name at all, so what the user sees is the LIST — which polls straight
    # after this and is where a reverted rename would show up.

    row = _row(db_conn, company_id)
    assert row["user_display_name"] == "Raindrop"
    assert row["health_state"] == "discovering", "the retry must still restart discovery"
    listed = client.get("/api/users/companies").json()["companies"]
    assert [c["displayName"] for c in listed] == ["Raindrop"]


def test_a_rename_survives_a_re_discovery(client, db_conn, monkeypatch):
    """The other clobber: ``_promote_to_tracked`` SETs ``display_name`` every time
    discovery accepts a board, so any re-discovery would overwrite a rename.

    Driven through the service function the discovery task calls, because the task
    itself opens a browser."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_discovered_company(client, monkeypatch)
    client.patch(f"/api/users/companies/{company_id}", json={"displayName": "Raindrop"})

    owner = db_conn.cursor()
    owner.execute(
        sql.SQL("SELECT user_id FROM {} WHERE company_id = %s").format(
            sql.Identifier("user_companies")
        ),
        (company_id,),
    )
    owning_user = str(owner.fetchone()["user_id"])

    promoted = svc.add_discovered_company(
        db_conn,
        user_id=owning_user,
        submitted_url=_NON_ATS_URL,
        normalized_url=_NON_ATS_URL,
        # The freshly DERIVED name the discovery task always passes.
        display_name="Acme",
        script={"kind": "http_json", "script_version": 1},
        transport="http_json",
        oracle_kind="self_consistent",
    )
    assert promoted is not None
    assert promoted["display_name"] == "Raindrop", (
        "the promote path's return value must carry the effective name, or the add "
        "response would render the derived one over a correctly-renamed row"
    )

    row = _row(db_conn, company_id)
    assert row["user_display_name"] == "Raindrop"
    assert row["display_name"] == "Acme", "the derived column is refreshed, as designed"
    listed = client.get("/api/users/companies").json()["companies"]
    assert [c["displayName"] for c in listed] == ["Raindrop"]


def test_an_un_renamed_board_still_shows_the_derived_name(client, db_conn, monkeypatch):
    """The COALESCE must be a fallback, not a replacement: a board nobody renamed reads
    exactly as it did before this shipped."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    derived = _row(db_conn, company_id)["display_name"]
    assert _row(db_conn, company_id)["user_display_name"] is None
    listed = client.get("/api/users/companies").json()["companies"]
    assert [c["displayName"] for c in listed] == [derived]


# --- Ownership is the security boundary -------------------------------------


def test_a_second_user_cannot_rename_someone_elses_company(
    client, db_conn, monkeypatch
):
    """AC-10's guarantee, extended to the new mutation: 404, not 403, so the response
    cannot be used to probe which company ids exist — the same answer DELETE gives.

    B IS A FULLY REAL USER HERE, with their own ``users`` row and their own tracked
    board, and that is the point rather than set dressing. Written the obvious way — B
    logs in and PATCHes without ever having added anything — this test PASSES even with
    the ownership predicate deleted from the UPDATE, because the router 404s earlier at
    "this email has no ``users`` row". It proved nothing about ownership at all. A
    mutation run caught exactly that.
    """
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    _login(client, "auth0|B", "b@example.com")
    b_company_id = _add_ats_company(client, monkeypatch)
    assert b_company_id != company_id, "two users adding one board get two rows"

    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": "Stolen"}
    )
    assert resp.status_code == 404, resp.text

    assert _row(db_conn, company_id)["user_display_name"] is None, (
        "B's attempt must have written nothing to A's row"
    )
    assert _row(db_conn, b_company_id)["user_display_name"] is None, (
        "and it must not have hit B's own row either — a WHERE clause that lost the "
        "id would rename the wrong board rather than none"
    )

    _login(client, "auth0|A", "a@example.com")
    listed = client.get("/api/users/companies").json()["companies"]
    assert len(listed) == 1, "A's board must survive B's attempt untouched"


def test_renaming_an_unknown_company_is_404(client, monkeypatch):
    """A REAL user asking for a company id that does not exist. The caller owns a board
    first for the same reason as above: without it the 404 would come from the
    no-``users``-row branch and this would not test the lookup."""
    _login(client, "auth0|A", "a@example.com")
    _add_ats_company(client, monkeypatch)
    resp = client.patch(
        "/api/users/companies/u-nosuchrow", json={"displayName": "Ghost"}
    )
    assert resp.status_code == 404


def test_a_public_company_cannot_be_renamed(client, db_conn, monkeypatch):
    """``visibility = 'user'`` in the UPDATE, tested through the worst case: an
    ownership row that points at a PUBLIC company. Without that predicate this would
    rename a board on everybody else's screen."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET visibility = 'public' WHERE id = %s").format(
            sql.Identifier("companies")
        ),
        (company_id,),
    )
    db_conn.commit()

    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": "Hijacked"}
    )
    assert resp.status_code == 404, resp.text
    assert _row(db_conn, company_id)["user_display_name"] is None


def test_rename_requires_the_feature_flag(client, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    monkeypatch.setattr(settings, "custom_company_sources_enabled", False)
    resp = client.patch("/api/users/companies/u-x", json={"displayName": "Nope"})
    assert resp.status_code == 503


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "submitted",
    ["   ", "\t\n", "​​", "‪‫"],
    ids=["spaces", "whitespace-controls", "zero-width", "bidi-controls"],
)
def test_a_name_with_nothing_visible_in_it_is_rejected(
    client, db_conn, monkeypatch, submitted
):
    """Every one of these is non-empty to Pydantic and empty to a reader. They must be
    a machine-readable 422, not a company row whose name renders as nothing."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": submitted}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "name_empty"
    assert _row(db_conn, company_id)["user_display_name"] is None


def test_a_name_over_the_cap_is_rejected_with_a_reason(client, db_conn, monkeypatch):
    """422 with a ``reason`` the UI can key copy off — a Pydantic ``Field`` violation
    would return a body with no ``reason`` and render generic copy instead."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": "x" * 101}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "name_too_long"
    assert isinstance(resp.json()["detail"], str) and resp.json()["detail"]
    assert _row(db_conn, company_id)["user_display_name"] is None


def test_a_name_exactly_at_the_cap_is_accepted(client, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": "x" * 100}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["displayName"] == "x" * 100


def test_the_name_is_trimmed_and_its_whitespace_collapsed(
    client, db_conn, monkeypatch
):
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    resp = client.patch(
        f"/api/users/companies/{company_id}",
        json={"displayName": "  Jane\tStreet   Capital  "},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["displayName"] == "Jane Street Capital"
    assert _row(db_conn, company_id)["user_display_name"] == "Jane Street Capital"


def test_invisible_characters_are_stripped_from_an_otherwise_real_name(
    client, db_conn, monkeypatch
):
    """The bidi override is the one that matters: it makes a stored name render in an
    order it is not stored in, which is how an escaped, un-injectable label can still
    lie about what it says."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)

    resp = client.patch(
        f"/api/users/companies/{company_id}",
        json={"displayName": "Acme‮gmp.exe"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["displayName"] == "Acmegmp.exe"
    assert "‮" not in _row(db_conn, company_id)["user_display_name"]


def test_ordinary_punctuation_and_accents_survive(client, monkeypatch):
    """The cleaner strips invisibles, not personality. A name that looks unusual is not
    a name that is dangerous — React escapes it on render."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    name = "O’Reilly & Sons <Café> \"Ltd\""
    resp = client.patch(
        f"/api/users/companies/{company_id}", json={"displayName": name}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["displayName"] == name


def test_an_unknown_body_field_is_rejected(client, monkeypatch):
    """``extra='forbid'``, same as every other request model on this router — a
    misspelled field must be a 422, not a silently ignored no-op rename."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    resp = client.patch(
        f"/api/users/companies/{company_id}",
        json={"displayName": "Fine", "visibility": "public"},
    )
    assert resp.status_code == 422


# --- Rate limiting ----------------------------------------------------------


def test_renames_are_rate_limited_on_their_own_bucket(client, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    monkeypatch.setattr(user_company_rename_rate_limiter, "_max", 2)

    codes = [
        client.patch(
            f"/api/users/companies/{company_id}", json={"displayName": f"N{i}"}
        ).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429], codes


def test_a_rename_does_not_consume_the_add_burst_limit(client, monkeypatch):
    """The two budgets are separate on purpose: a rename opens no browser and makes no
    outbound request, so it must not eat a slot the add path needs."""
    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    user_company_add_rate_limiter.reset()
    monkeypatch.setattr(user_company_add_rate_limiter, "_max", 1)

    for i in range(5):
        assert (
            client.patch(
                f"/api/users/companies/{company_id}", json={"displayName": f"N{i}"}
            ).status_code
            == 200
        )

    # The one add slot is still there, unspent by five renames.
    _install_greenhouse(monkeypatch, [3])
    assert (
        client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/duolingo"}
        ).status_code
        == 200
    )


def test_a_rename_does_not_consume_the_monthly_cap(client, db_conn, monkeypatch):
    """The monthly cap is the SPEND guard. A rename spends nothing, so the counter the
    Add Companies page renders must not move."""
    from api.services import add_quota

    _login(client, "auth0|A", "a@example.com")
    company_id = _add_ats_company(client, monkeypatch)
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT user_id FROM {} WHERE company_id = %s").format(
            sql.Identifier("user_companies")
        ),
        (company_id,),
    )
    user_id = str(cur.fetchone()["user_id"])
    before = add_quota.get_quota(db_conn, user_id, email="a@example.com").used

    for i in range(3):
        client.patch(
            f"/api/users/companies/{company_id}", json={"displayName": f"N{i}"}
        )

    assert add_quota.get_quota(db_conn, user_id, email="a@example.com").used == before
