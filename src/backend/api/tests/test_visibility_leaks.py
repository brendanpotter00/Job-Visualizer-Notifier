"""E7 §5 — the three private-company visibility leaks + the fan-out gate.

A ``visibility='user'`` company must be invisible on every UNAUTHENTICATED or
cross-user surface:
  1. the public curated directory ``GET /api/companies``,
  2. the public ``GET /api/jobs`` list AND single-job detail,
  3. the auto-enroll UNION (never pulled into another user's feed), and
  4. the six ATS fan-outs (``list_enabled_companies(conn, ats)``).

Leak 5 (added with the Recent-feed integration) covers the SECOND authed path
that serves private jobs — ``GET /api/users/companies/jobs`` — which must stay
owner-scoped without weakening any of the four above.

Leak 6 covers ``GET /api/jobs/search``, the Recent page's read path. It is a
THIRD public reader over ``job_listings``, added after leaks 1-4 were written and
therefore not covered by any of them — which is the point: this file enumerates
surfaces by hand, so a new public reader is invisible to it until someone adds a
case. It leaks in three distinct ways if unguarded (rows, ``filteredTotal``, and
the two recency tiles), and all three are asserted below.

Leak 6b is the OTHER side of leak 6: that same reader now serves a signed-in
caller their OWN private boards (the Recent page's only read path, so without it
a custom company is invisible to the person who added it). The hole is scoped by
a server-derived ownership set, never by anything on the request, and 6b reads one
fixture four ways — anonymous, owning-nothing, owning-something-else, owner — to
prove only the last one sees it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from psycopg2 import sql

from scripts.shared.constants import (
    CUSTOM_SOURCE_PREFIX,
    RECIPE_ATS,
    RECIPE_SOURCE_PREFIX,
    custom,
    recipe,
)
from api.auth.dependencies import get_current_user, get_optional_user_lenient
from api.config import settings
from scripts.shared.database import (
    list_enabled_companies as list_ats_enabled_companies,
)
from api.services.user_preferences_service import (
    list_enabled_companies as list_user_enabled_companies,
)
from api.services.database import get_job_by_id, get_jobs, get_user_company_jobs


def _insert_company(
    conn,
    company_id: str,
    *,
    visibility: str = "public",
    enabled: bool = True,
    ats: str = "greenhouse",
    board_token: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, ats, board_token or company_id, enabled, visibility),
    )
    conn.commit()


def _insert_job(
    conn,
    job_id: str,
    company: str,
    source_id: str,
    *,
    status: str = "OPEN",
    first_seen_at: str = "2025-01-01T00:00:00Z",
) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("job_listings")),
        (
            job_id, "Engineer", company, "https://x/1", source_id,
            first_seen_at, first_seen_at, status,
        ),
    )
    conn.commit()


def _insert_user(conn, user_id: str, email: str, *, watermark: str = "2020-01-01T00:00:00Z") -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at, "
            "company_enroll_watermark, auto_enroll_new_companies) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE)"
        ).format(sql.Identifier("users")),
        (user_id, f"auth0|{user_id}", email, "2020-01-01T00:00:00Z",
         "2020-01-01T00:00:00Z", watermark),
    )
    conn.commit()


# --- Leak 1: public directory -------------------------------------------------


def test_public_directory_omits_user_company(client, db_conn):
    _insert_company(db_conn, "pub-co", visibility="public")
    _insert_company(db_conn, "priv-co", visibility="user")

    resp = client.get("/api/companies")
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.json()["companies"]}
    assert "pub-co" in ids
    assert "priv-co" not in ids


# --- Leak 2: public /api/jobs list + detail ----------------------------------


def test_public_jobs_list_omits_user_company(client, db_conn):
    _insert_company(db_conn, "pub-co", visibility="public")
    _insert_company(db_conn, "u-private01", visibility="user")
    _insert_job(db_conn, "1", "pub-co", "greenhouse_api")
    _insert_job(db_conn, "2", "u-private01", custom("u-private01"))

    # Filtered to the private company → empty for an anonymous caller.
    resp = client.get("/api/jobs", params={"company": "u-private01"})
    assert resp.status_code == 200
    assert resp.json() == []

    # Unfiltered list must not contain the private company's job either.
    resp_all = client.get("/api/jobs")
    assert resp_all.status_code == 200
    companies = {j["company"] for j in resp_all.json()}
    assert "u-private01" not in companies
    assert "pub-co" in companies


def test_public_job_detail_of_user_company_is_404(client, db_conn):
    _insert_company(db_conn, "u-private01", visibility="user")
    _insert_job(db_conn, "77", "u-private01", custom("u-private01"))

    resp = client.get(f"/api/jobs/{custom('u-private01')}/77")
    assert resp.status_code == 404


def test_public_job_detail_of_public_company_still_works(client, db_conn):
    _insert_company(db_conn, "pub-co", visibility="public")
    _insert_job(db_conn, "88", "pub-co", "greenhouse_api")

    resp = client.get("/api/jobs/greenhouse_api/88")
    assert resp.status_code == 200
    assert resp.json()["id"] == "88"


def test_service_layer_read_paths_never_return_a_user_company_job(db_conn):
    """The same guard as the two HTTP cases above, one layer down.

    Those go through the router; this asserts the property where it is actually
    implemented (``_USER_COMPANY_PREDICATE``, applied unconditionally by
    ``_build_where`` and ``get_job_by_id``). It therefore still fails if someone
    rewires the router, adds a second public router, or gives either reader a
    viewer argument — which is the exact "conditional leak that passes review"
    the predicate's own comment warns about.
    """
    _insert_company(db_conn, "svc-pub", visibility="public")
    _insert_company(db_conn, "u-svcpriv01", visibility="user")
    _insert_job(db_conn, "svc-1", "svc-pub", "greenhouse_api")
    _insert_job(db_conn, "svc-2", "u-svcpriv01", custom("u-svcpriv01"))

    # Unfiltered list.
    companies = {j["company"] for j in get_jobs(db_conn)}
    assert "svc-pub" in companies
    assert "u-svcpriv01" not in companies

    # Explicitly asking for the private company by name.
    assert get_jobs(db_conn, company="u-svcpriv01") == []
    assert get_jobs(db_conn, companies=["u-svcpriv01", "svc-pub"]) != []
    assert {j["company"] for j in get_jobs(db_conn, companies=["u-svcpriv01", "svc-pub"])} == {
        "svc-pub"
    }

    # Single-job detail, by its exact composite key.
    assert get_job_by_id(db_conn, custom("u-svcpriv01"), "svc-2") is None
    assert get_job_by_id(db_conn, "greenhouse_api", "svc-1") is not None

    # ...and the row genuinely exists — the owner-scoped reader, which is the
    # ONLY path allowed to see it, returns it.
    owned = get_user_company_jobs(db_conn, "u-svcpriv01", custom("u-svcpriv01"))
    assert {j["id"] for j in owned} == {"svc-2"}


# --- Leak 3: auto-enroll UNION -----------------------------------------------


def test_auto_enroll_excludes_user_company(db_conn):
    user_id = uuid.uuid4().hex
    _insert_user(db_conn, user_id, "enroll@example.com")
    # Give the user one explicit row so the auto-enroll EXISTS branch fires.
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO user_enabled_companies (user_id, company_id) VALUES (%s, %s)",
        (user_id, "already-enabled"),
    )
    db_conn.commit()

    # Both created AFTER the user's watermark (default now() > 2020).
    _insert_company(db_conn, "new-public", visibility="public")
    _insert_company(db_conn, "new-private", visibility="user")

    enrolled = list_user_enabled_companies(db_conn, user_id)
    assert "new-public" in enrolled       # public auto-enrolls
    assert "new-private" not in enrolled  # private must NOT
    assert "already-enabled" in enrolled  # explicit row still there


# --- Leak 4: the ATS fan-out --------------------------------------------------


def test_ats_fan_out_excludes_user_company(db_conn):
    _insert_company(db_conn, "pub-gh", visibility="public", ats="greenhouse", board_token="pubtok")
    _insert_company(db_conn, "u-privgh01", visibility="user", ats="greenhouse", board_token="privtok")

    rows = list_ats_enabled_companies(db_conn, "greenhouse")
    ids = {r["id"] for r in rows}
    assert "pub-gh" in ids
    assert "u-privgh01" not in ids


# --- Leak 5: the owner-scoped Recent-feed union ------------------------------
#
# ``GET /api/users/companies/jobs`` is what puts a user's private boards on the
# Recent Jobs page. It is the SECOND path that serves ``visibility='user'`` jobs,
# so it needs the same three-way proof the per-company path has: anonymous sees
# nothing, a signed-in NON-owner sees nothing, and the owner sees their own. The
# first two are the ones that can silently stop asserting anything — a fixture
# that quietly failed to log anyone in would make "non-owner sees nothing" pass
# forever, so each test also asserts the POSITIVE half on the same data.


@pytest.fixture
def flag_on(monkeypatch):
    """The endpoint 503s with the feature flag off, which would make every leak
    assertion below vacuously true. Turn it ON so the tests prove the guard, not
    the kill switch."""
    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)


def _own(conn, user_id: str, company_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) "
            "VALUES (%s, %s, %s)"
        ).format(sql.Identifier("user_companies")),
        (user_id, company_id, f"greenhouse:{company_id}"),
    )
    conn.commit()


def _login_as(client, email: str) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: {
        "sub": f"auth0|{email}", "email": email,
        "given_name": "A", "family_name": "B", "picture": None,
    }


def test_owner_feed_serves_only_the_callers_own_private_jobs(client, db_conn, flag_on):
    owner_id = uuid.uuid4().hex
    other_id = uuid.uuid4().hex
    _insert_user(db_conn, owner_id, f"{owner_id}@example.com")
    _insert_user(db_conn, other_id, f"{other_id}@example.com")
    _insert_company(db_conn, "u-feedown01", visibility="user")
    _insert_company(db_conn, "u-feedoth01", visibility="user")
    _own(db_conn, owner_id, "u-feedown01")
    _own(db_conn, other_id, "u-feedoth01")
    _insert_job(db_conn, "mine", "u-feedown01", custom("u-feedown01"))
    _insert_job(db_conn, "theirs", "u-feedoth01", custom("u-feedoth01"))

    original = client.app.dependency_overrides.get(get_current_user)
    try:
        _login_as(client, f"{owner_id}@example.com")
        ids = {j["id"] for j in client.get("/api/users/companies/jobs").json()}
        assert ids == {"mine"}, "owner must see their own board and nothing else"

        # Signed in, but owns a DIFFERENT private company: the other user's job
        # must not appear. This is the cross-user leak.
        _login_as(client, f"{other_id}@example.com")
        ids_other = {j["id"] for j in client.get("/api/users/companies/jobs").json()}
        assert ids_other == {"theirs"}
    finally:
        if original is not None:
            client.app.dependency_overrides[get_current_user] = original


def test_owner_feed_is_401_for_anonymous(client, db_conn, flag_on):
    _insert_user(db_conn, "feedanonusr", "feedanon@example.com")
    _insert_company(db_conn, "u-feedanon1", visibility="user")
    _own(db_conn, "feedanonusr", "u-feedanon1")
    _insert_job(db_conn, "anon-secret", "u-feedanon1", custom("u-feedanon1"))

    original = client.app.dependency_overrides.pop(get_current_user, None)
    try:
        resp = client.get("/api/users/companies/jobs")
        assert resp.status_code == 401
        assert "anon-secret" not in resp.text
    finally:
        if original is not None:
            client.app.dependency_overrides[get_current_user] = original
            # The same row IS served to its owner — proof the 401 above came from
            # the auth gate, not from an empty fixture.
            _login_as(client, "feedanon@example.com")
            ids = {j["id"] for j in client.get("/api/users/companies/jobs").json()}
            assert "anon-secret" in ids
            client.app.dependency_overrides[get_current_user] = original


def test_public_jobs_list_still_omits_private_jobs_after_the_feed_endpoint_exists(
    client, db_conn, flag_on
):
    """The regression guard for the tempting-but-wrong fix: making the Recent feed
    work by relaxing ``_USER_COMPANY_PREDICATE`` on ``/api/jobs``. That endpoint
    is unauthenticated and forwarded verbatim by ``api/jobs.ts``, so its guard
    must stay UNCONDITIONAL no matter who is asking."""
    user_id = uuid.uuid4().hex
    _insert_user(db_conn, user_id, f"{user_id}@example.com")
    _insert_company(db_conn, "u-feedpub01", visibility="user")
    _own(db_conn, user_id, "u-feedpub01")
    _insert_job(db_conn, "still-private", "u-feedpub01", custom("u-feedpub01"))

    original = client.app.dependency_overrides.get(get_current_user)
    try:
        # Even with the owner "signed in", the PUBLIC endpoint serves nothing.
        _login_as(client, f"{user_id}@example.com")
        assert client.get("/api/jobs", params={"company": "u-feedpub01"}).json() == []
        assert client.get(
            f"/api/jobs/{custom('u-feedpub01')}/still-private"
        ).status_code == 404
        # ...while the authed feed does serve it, proving the row exists at all.
        ids = {j["id"] for j in client.get("/api/users/companies/jobs").json()}
        assert "still-private" in ids
    finally:
        if original is not None:
            client.app.dependency_overrides[get_current_user] = original


# --- Leak 6: the public /api/jobs/search reader -------------------------------
#
# ``GET /api/jobs/search`` is unauthenticated (the handler takes only
# ``Depends(get_db)``) and is allow-listed through the public Vercel proxy, so it
# is a public read path in exactly the sense ``_USER_COMPANY_PREDICATE`` means.
#
# It shipped applying only ``_HIDDEN_COMPANY_PREDICATE`` — the disabled-company
# guard — because it was authored before ``companies.visibility`` existed. Git
# merged the two branches without complaint (disjoint files) and every existing
# test above still passed, because none of them had any notion of this route.
# That is the failure mode these cases exist to make loud.


def test_public_jobs_search_omits_user_company(client, db_conn):
    _insert_company(db_conn, "srch-pub", visibility="public")
    _insert_company(db_conn, "u-srchpriv01", visibility="user")
    _insert_job(db_conn, "s1", "srch-pub", "greenhouse_api")
    _insert_job(db_conn, "s2", "u-srchpriv01", custom("u-srchpriv01"))

    resp = client.get("/api/jobs/search")
    assert resp.status_code == 200
    companies = {j["company"] for j in resp.json()["jobs"]}
    assert "srch-pub" in companies
    assert "u-srchpriv01" not in companies


def test_public_jobs_search_cannot_target_a_private_board_by_name(client, db_conn):
    """``ENABLED_COMPANY_ID_PATTERN`` admits ``u-<base36>``, so a private board's
    id is a syntactically valid ``?company=`` value. Asking for one by name must
    return nothing rather than that board's whole feed."""
    _insert_company(db_conn, "u-srchpriv02", visibility="user")
    _insert_job(db_conn, "s3", "u-srchpriv02", custom("u-srchpriv02"))

    resp = client.get("/api/jobs/search", params={"company": "u-srchpriv02"})
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


def test_public_jobs_search_counts_exclude_user_company(client, db_conn):
    """The tiles and the total are separate SQL from the row query.

    ``filtered_total`` and the two recency counts come from
    ``get_search_counts`` / ``_header_counts_where``, not from the page query, so
    guarding only ``build_search_where`` would still publish the SIZE of someone
    else's private board above a list that correctly hides it.
    """
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _insert_company(db_conn, "srch-pub2", visibility="public")
    _insert_company(db_conn, "u-srchpriv03", visibility="user")
    _insert_job(db_conn, "s4", "srch-pub2", "greenhouse_api", first_seen_at=fresh)
    # TWO private rows, both inside the 24h window: if the tile were unguarded it
    # would read 3, so this assertion cannot pass by accident.
    _insert_job(db_conn, "s5", "u-srchpriv03", custom("u-srchpriv03"), first_seen_at=fresh)
    _insert_job(db_conn, "s6", "u-srchpriv03", custom("u-srchpriv03"), first_seen_at=fresh)

    meta = client.get("/api/jobs/search").json()["meta"]
    assert meta["filteredTotal"] is None
    assert meta["countLast24h"] == 1


def test_search_service_layer_never_returns_a_user_company_job(db_conn):
    """The property where it is implemented, one layer below the router.

    Mirrors ``test_service_layer_read_paths_never_return_a_user_company_job`` for
    the search reader: it still fails if someone rewires the router or mounts a
    second one.

    THE DEFAULT IS THE INVARIANT. ``search_jobs`` now takes an
    ``owned_source_ids`` scope (Leak 6b below), so "no viewer argument exists" is
    no longer the thing being asserted — what is asserted is that OMITTING it
    yields the blanket guard, unchanged. That is the state every anonymous
    request is in, so a regression that inverted the default would fail here.
    Leak 6b covers the other half: that supplying a scope widens the read by
    exactly the caller's own rows and nothing else.
    """
    from api.services.job_search import get_search_counts, search_jobs

    _insert_company(db_conn, "svc-srch-pub", visibility="public")
    _insert_company(db_conn, "u-svcsrch01", visibility="user")
    _insert_job(db_conn, "sv1", "svc-srch-pub", "greenhouse_api")
    _insert_job(db_conn, "sv2", "u-svcsrch01", custom("u-svcsrch01"))

    rows = search_jobs(db_conn, status="OPEN", limit=100)
    companies = {r["company"] for r in rows}
    assert "svc-srch-pub" in companies
    assert "u-svcsrch01" not in companies

    counts = get_search_counts(db_conn, status="OPEN")
    assert counts["filtered_total"] is None


# --- Leak 6b: the OWNER-scoped relaxation of the search reader ----------------
#
# The counterpart to Leak 6. Leak 6 proves the blanket guard; these prove the one
# sanctioned hole in it does not become a leak.
#
# WHY THE HOLE EXISTS. The Recent Jobs page migrated to ``GET /api/jobs/search``
# and left behind the client-side merge of the authed
# ``GET /api/users/companies/jobs`` that used to put a reader's own private boards
# in their feed. The unconditional predicate then hid those boards from their own
# OWNER: discovery succeeded, the harvest wrote the rows, and the feed showed none
# of them.
#
# WHY IT IS NOT THE "conditional leak" THE PREDICATE WARNS ABOUT. The scope is
# never request-derived. It is computed from ``user_companies`` against a
# validated token (``_resolve_owned_source_ids`` -> ``list_owned_source_ids``), so
# a caller cannot name a namespace they do not own — no parameter reaches it.
# These cases pin that: one fixture is read four ways (anonymous, a signed-in user
# owning nothing, a signed-in user owning a DIFFERENT board, and the owner) and
# only the owner ever sees the row.


def _login_optional_as(client, email: str) -> None:
    """Sign in for the SEARCH endpoint specifically.

    ``/api/jobs/search`` resolves its viewer through ``get_optional_user_lenient``
    (a public endpoint must degrade a stale token to anonymous, not 401 the whole
    feed), which is a DIFFERENT dependency from the ``get_current_user`` that
    ``_login_as`` overrides. Overriding the wrong one would leave every request
    anonymous and make the negatives below pass vacuously — which is why every
    negative case here is asserted alongside the owner's positive on the SAME
    fixture.
    """
    client.app.dependency_overrides[get_optional_user_lenient] = lambda: {
        "sub": f"auth0|{email}", "email": email,
        "given_name": "A", "family_name": "B", "picture": None,
    }


def _logout_optional(client) -> None:
    client.app.dependency_overrides.pop(get_optional_user_lenient, None)


def test_search_serves_the_owners_own_private_board_to_the_owner(client, db_conn):
    """The bug this fixes: the owner could not see their own custom jobs."""
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "srch-pub6b", visibility="public")
    _insert_company(db_conn, "u-own6b0001", visibility="user")
    _own(db_conn, owner_id, "u-own6b0001")
    _insert_job(db_conn, "own-6b-1", "srch-pub6b", "greenhouse_api")
    _insert_job(db_conn, "own-6b-2", "u-own6b0001", custom("u-own6b0001"))

    try:
        _login_optional_as(client, email)
        resp = client.get("/api/jobs/search")
        assert resp.status_code == 200
        ids = {j["id"] for j in resp.json()["jobs"]}
        assert "own-6b-2" in ids, "owner must see their OWN private board"
        assert "own-6b-1" in ids, "...without losing the public corpus"
    finally:
        _logout_optional(client)


def test_search_owner_can_target_their_own_board_by_name(client, db_conn):
    """The ``?company=`` path Leak 6 proves returns nothing for a stranger.

    Same request, same id, opposite expectation purely because of who is asking —
    which is the entire point of the scope.
    """
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "u-own6b0002", visibility="user")
    _own(db_conn, owner_id, "u-own6b0002")
    _insert_job(db_conn, "own-6b-3", "u-own6b0002", custom("u-own6b0002"))

    try:
        _login_optional_as(client, email)
        owned = client.get("/api/jobs/search", params={"company": "u-own6b0002"})
        assert owned.status_code == 200
        assert {j["id"] for j in owned.json()["jobs"]} == {"own-6b-3"}
    finally:
        _logout_optional(client)

    # ...and the identical request, signed out, still returns nothing.
    anon = client.get("/api/jobs/search", params={"company": "u-own6b0002"})
    assert anon.status_code == 200
    assert anon.json()["jobs"] == []


def test_search_hides_a_private_board_from_anonymous_and_from_other_users(
    client, db_conn
):
    """The privacy half, read FOUR ways off one fixture.

    The owner assertion is the control: without it, a fixture that silently failed
    to insert the row (or to sign anyone in) would make all three negatives pass
    forever while proving nothing.
    """
    owner_id = uuid.uuid4().hex
    nobody_id = uuid.uuid4().hex
    rival_id = uuid.uuid4().hex
    _insert_user(db_conn, owner_id, f"{owner_id}@example.com")
    _insert_user(db_conn, nobody_id, f"{nobody_id}@example.com")
    _insert_user(db_conn, rival_id, f"{rival_id}@example.com")
    _insert_company(db_conn, "u-own6b0003", visibility="user")
    _insert_company(db_conn, "u-riv6b0003", visibility="user")
    _own(db_conn, owner_id, "u-own6b0003")
    _own(db_conn, rival_id, "u-riv6b0003")
    _insert_job(db_conn, "secret-6b", "u-own6b0003", custom("u-own6b0003"))
    _insert_job(db_conn, "rival-6b", "u-riv6b0003", custom("u-riv6b0003"))

    try:
        # 1. ANONYMOUS — sees neither private row.
        _logout_optional(client)
        anon = client.get("/api/jobs/search")
        assert anon.status_code == 200
        assert "secret-6b" not in anon.text
        assert "rival-6b" not in anon.text

        # 2. Signed in, owns NOTHING — the scope is empty, so the blanket guard
        #    applies exactly as it does for an anonymous caller.
        _login_optional_as(client, f"{nobody_id}@example.com")
        nobody = client.get("/api/jobs/search")
        assert nobody.status_code == 200
        assert "secret-6b" not in nobody.text
        assert "rival-6b" not in nobody.text

        # 3. Signed in, owns a DIFFERENT private board — the cross-user leak. Sees
        #    theirs, never the owner's. This is the case a request-derived scope
        #    would get wrong.
        _login_optional_as(client, f"{rival_id}@example.com")
        rival_ids = {j["id"] for j in client.get("/api/jobs/search").json()["jobs"]}
        assert "rival-6b" in rival_ids
        assert "secret-6b" not in rival_ids

        # 4. The OWNER — the control. The row was there the whole time.
        _login_optional_as(client, f"{owner_id}@example.com")
        owner_ids = {j["id"] for j in client.get("/api/jobs/search").json()["jobs"]}
        assert "secret-6b" in owner_ids
        assert "rival-6b" not in owner_ids
    finally:
        _logout_optional(client)


def test_search_recency_tiles_follow_the_same_scope_as_the_rows(client, db_conn):
    """The tiles are separate SQL (``_header_counts_where``) and must agree.

    Both directions are a bug. Counting a private row the list hides publishes the
    SIZE of someone else's board (Leak 6). NOT counting the owner's own row while
    the list shows it puts the tile UNDER the feed beneath it — the same
    disagreement, and the one a fix that touched only ``build_search_where`` ships.
    """
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "srch-pub6c", visibility="public")
    _insert_company(db_conn, "u-own6b0004", visibility="user")
    _insert_company(db_conn, "u-oth6b0004", visibility="user")
    _own(db_conn, owner_id, "u-own6b0004")
    _insert_job(db_conn, "t1", "srch-pub6c", "greenhouse_api", first_seen_at=fresh)
    _insert_job(db_conn, "t2", "u-own6b0004", custom("u-own6b0004"), first_seen_at=fresh)
    # Someone else's private row, same window: never counted, for anyone.
    _insert_job(db_conn, "t3", "u-oth6b0004", custom("u-oth6b0004"), first_seen_at=fresh)

    anon_meta = client.get("/api/jobs/search").json()["meta"]
    assert anon_meta["countLast24h"] == 1, "anonymous counts only the public row"

    try:
        _login_optional_as(client, email)
        body = client.get("/api/jobs/search").json()
        assert body["meta"]["countLast24h"] == 2, (
            "owner counts the public row + their OWN private row, never the third"
        )
        # The tile matches the rows it sits above.
        assert {j["id"] for j in body["jobs"]} == {"t1", "t2"}
    finally:
        _logout_optional(client)


def test_search_cursor_minted_signed_in_is_409_when_replayed_anonymously(
    client, db_conn
):
    """A cursor carries the VISIBILITY SCOPE it was minted under.

    A token expiring mid-walk turns a signed-in walk anonymous with no client
    involvement. Without the scope in the fingerprint that cursor stays valid, the
    owner's rows silently drop out from page N on, and the walk enumerates neither
    scope completely — exactly what the fingerprint exists to turn into a restart.
    """
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "u-own6b0005", visibility="user")
    _own(db_conn, owner_id, "u-own6b0005")
    _insert_company(db_conn, "srch-pub6d", visibility="public")
    for i in range(3):
        _insert_job(db_conn, f"c{i}", "srch-pub6d", "greenhouse_api")

    try:
        _login_optional_as(client, email)
        page1 = client.get("/api/jobs/search", params={"limit": 1})
        assert page1.status_code == 200
        cursor = page1.json()["nextCursor"]
        assert cursor, "need a full page to mint a cursor"
    finally:
        _logout_optional(client)

    replayed = client.get("/api/jobs/search", params={"limit": 1, "cursor": cursor})
    assert replayed.status_code == 409, (
        "a signed-in cursor replayed anonymously must 409, not silently re-scope"
    )


def test_search_cursor_minted_and_replayed_anonymously_walks_every_page(
    client, db_conn
):
    """THE NO-REGRESSION CASE, and the one with the widest blast radius.

    The visibility scope joined the cursor fingerprint in this change, and the
    scope of an anonymous reader has two spellings in the code — ``None`` from
    ``_resolve_owned_source_ids`` and the ``[]`` the router canonicalizes it to.
    If those two ever hashed differently, page 2 would be a 409 for every
    signed-out visitor on the site: a far worse failure than the one this branch
    fixes, and invisible to every owner-side test above.

    Asserted as a WALK rather than as "page 2 returned 200", because a cursor
    that validates and then seeks to the wrong place is also a 200.
    """
    _insert_company(db_conn, "srch-pub6e", visibility="public")
    for i in range(3):
        _insert_job(db_conn, f"w{i}", "srch-pub6e", "greenhouse_api")

    _logout_optional(client)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(6):
        params: dict = {"limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get("/api/jobs/search", params=params)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        seen.extend(j["id"] for j in body["jobs"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert cursor is None, "the anonymous walk never terminated"
    assert seen == ["w2", "w1", "w0"], (
        "an anonymous keyset walk must still enumerate every row exactly once, "
        "in (first_seen_at, source_id, id) DESC order"
    )


def test_search_cursor_minted_by_the_owner_replays_for_the_same_owner(
    client, db_conn
):
    """The signed-in mirror of the case above.

    Same requirement, different scope: a walk whose scope did not move must not
    409, and the owner's own private row has to survive the page boundary rather
    than appearing on page 1 and vanishing afterwards.
    """
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "srch-pub6f", visibility="public")
    _insert_company(db_conn, "u-own6b0006", visibility="user")
    _own(db_conn, owner_id, "u-own6b0006")
    _insert_job(db_conn, "p-1", "srch-pub6f", "greenhouse_api")
    _insert_job(db_conn, "p-2", "srch-pub6f", "greenhouse_api")
    _insert_job(db_conn, "priv-1", "u-own6b0006", custom("u-own6b0006"))

    try:
        _login_optional_as(client, email)
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(6):
            params: dict = {"limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            resp = client.get("/api/jobs/search", params=params)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            seen.extend(j["id"] for j in body["jobs"])
            cursor = body["nextCursor"]
            if cursor is None:
                break

        assert cursor is None, "the owner's walk never terminated"
        assert sorted(seen) == ["p-1", "p-2", "priv-1"], (
            "the owner's own private row must survive the page boundary"
        )
    finally:
        _logout_optional(client)


def test_search_cursor_minted_by_one_owner_is_409_for_a_different_owner(
    client, db_conn
):
    """CROSS-SCOPE replay — the direction the anonymous case cannot reach.

    Two signed-in readers owning DIFFERENT boards are walking two different
    queries, so one's cursor must not be honoured for the other. The final
    assertion is the control: the SAME cursor is still accepted for the reader
    who minted it, so the 409 above is the scope moving and not a cursor this
    endpoint would have rejected from anybody.
    """
    owner_id = uuid.uuid4().hex
    rival_id = uuid.uuid4().hex
    _insert_user(db_conn, owner_id, f"{owner_id}@example.com")
    _insert_user(db_conn, rival_id, f"{rival_id}@example.com")
    _insert_company(db_conn, "srch-pub6g", visibility="public")
    _insert_company(db_conn, "u-own6b0007", visibility="user")
    _insert_company(db_conn, "u-riv6b0007", visibility="user")
    _own(db_conn, owner_id, "u-own6b0007")
    _own(db_conn, rival_id, "u-riv6b0007")
    for i in range(3):
        _insert_job(db_conn, f"x{i}", "srch-pub6g", "greenhouse_api")

    try:
        _login_optional_as(client, f"{owner_id}@example.com")
        page1 = client.get("/api/jobs/search", params={"limit": 1})
        assert page1.status_code == 200, page1.text
        cursor = page1.json()["nextCursor"]
        assert cursor, "need a full page to mint a cursor"

        _login_optional_as(client, f"{rival_id}@example.com")
        rival = client.get("/api/jobs/search", params={"limit": 1, "cursor": cursor})
        assert rival.status_code == 409, (
            "a cursor minted under one reader's owned set must not be honoured "
            f"for another's; got {rival.status_code}: {rival.text}"
        )

        _login_optional_as(client, f"{owner_id}@example.com")
        again = client.get("/api/jobs/search", params={"limit": 1, "cursor": cursor})
        assert again.status_code == 200, (
            "the control failed: the cursor is not accepted even for the reader "
            f"who minted it, so the 409 above proves nothing. {again.text}"
        )
    finally:
        _logout_optional(client)


def test_search_cursor_minted_anonymously_is_409_once_the_reader_signs_in(
    client, db_conn
):
    """Signing IN mid-walk moves the scope too — the mirror of the expiry case.

    Without it the reader's own boards would start appearing partway through a
    walk that had already passed their position, so the pages would enumerate
    neither scope completely while every cursor kept validating.
    """
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "srch-pub6h", visibility="public")
    _insert_company(db_conn, "u-own6b0008", visibility="user")
    _own(db_conn, owner_id, "u-own6b0008")
    for i in range(3):
        _insert_job(db_conn, f"y{i}", "srch-pub6h", "greenhouse_api")

    _logout_optional(client)
    page1 = client.get("/api/jobs/search", params={"limit": 1})
    assert page1.status_code == 200, page1.text
    cursor = page1.json()["nextCursor"]
    assert cursor, "need a full page to mint a cursor"

    try:
        _login_optional_as(client, email)
        signed_in = client.get(
            "/api/jobs/search", params={"limit": 1, "cursor": cursor}
        )
        assert signed_in.status_code == 409, signed_in.text
    finally:
        _logout_optional(client)

    # The control: still anonymous, the same cursor is fine.
    anon = client.get("/api/jobs/search", params={"limit": 1, "cursor": cursor})
    assert anon.status_code == 200, anon.text


def test_an_empty_owned_scope_emits_the_shipped_sql_byte_for_byte(db_conn):
    """The no-regression proof for every reader who owns nothing.

    The relaxed predicate is opt-in on a NON-EMPTY scope, and "byte-identical
    otherwise" is the whole reason the Leak-6 cases above still mean what they
    meant. This asserts it against the composed SQL instead of restating the
    claim in a comment: all three empty spellings — the argument omitted, ``None``
    and ``[]`` — must compose to the same text and the same parameters.

    An ``if owned_source_ids is not None`` slip would type-check, keep every
    owner test green, and hand the array branch to every anonymous reader on the
    site. The inequality assertions at the end are what stop this from passing
    vacuously for an implementation that ignored the scope entirely.
    """
    from api.services.job_search import _header_counts_where, build_search_where

    omitted_sql, omitted_params = build_search_where(status="OPEN")
    none_sql, none_params = build_search_where(status="OPEN", owned_source_ids=None)
    empty_sql, empty_params = build_search_where(status="OPEN", owned_source_ids=[])
    scoped_sql, scoped_params = build_search_where(
        status="OPEN", owned_source_ids=["custom:u-scope0001"]
    )

    baseline = omitted_sql.as_string(db_conn)
    assert none_sql.as_string(db_conn) == baseline
    assert empty_sql.as_string(db_conn) == baseline
    assert omitted_params == none_params == empty_params == ["OPEN"]
    assert "job_listings.source_id = ANY" not in baseline, (
        f"the empty scope emitted the owner branch anyway:\n{baseline}"
    )
    assert "c.visibility = 'user'" in baseline, (
        f"the blanket private-company guard is gone:\n{baseline}"
    )
    assert scoped_sql.as_string(db_conn) != baseline
    assert scoped_params == ["OPEN", ["custom:u-scope0001"]]

    # The tiles are separate SQL and get the identical guarantee — a fix that
    # touched only the page query would pass everything above.
    tiles_baseline = _header_counts_where(None)[0].as_string(db_conn)
    assert _header_counts_where(None, None)[0].as_string(db_conn) == tiles_baseline
    assert _header_counts_where(None, [])[0].as_string(db_conn) == tiles_baseline
    assert (
        _header_counts_where(None)[1]
        == _header_counts_where(None, None)[1]
        == _header_counts_where(None, [])[1]
        == []
    )
    assert "job_listings.source_id = ANY" not in tiles_baseline, tiles_baseline
    tiles_scoped_sql, tiles_scoped_params = _header_counts_where(
        None, ["custom:u-scope0001"]
    )
    assert tiles_scoped_sql.as_string(db_conn) != tiles_baseline
    assert tiles_scoped_params == [["custom:u-scope0001"]]


def test_the_visibility_scope_hashes_order_and_duplicate_independently():
    """The scope is a SET, and the fingerprint has to treat it as one.

    ``list_owned_source_ids`` returns rows in whatever order the planner hands
    back — no ``ORDER BY`` — and a board co-owned through two ``user_companies``
    rows would repeat. Either would move the fingerprint if it were hashed
    positionally, and the symptom is a reader 409ing their OWN walk between two
    pages that asked for exactly the same thing.

    ``compute_filter_fingerprint`` sorts and de-duplicates every list value; this
    pins that the scope is carried as a list and therefore gets that treatment,
    rather than being folded in as a pre-joined string somewhere upstream.
    """
    from api.pagination import compute_filter_fingerprint

    def fp(scope: list[str]) -> str:
        return compute_filter_fingerprint({"owned_sources": scope})

    assert fp(["custom:u-b", "custom:u-a"]) == fp(["custom:u-a", "custom:u-b"])
    assert fp(["custom:u-a", "custom:u-a"]) == fp(["custom:u-a"])
    # ...and it is not a constant function: an empty scope is a DIFFERENT query.
    assert fp([]) != fp(["custom:u-a"])


def test_search_response_is_marked_uncacheable_because_it_varies_by_viewer(
    client, db_conn
):
    """A viewer-dependent body has to SAY it is viewer-dependent.

    Since the owner scope landed, the same query string returns different rows
    for different ``Authorization`` headers — one of them carrying that reader's
    own private boards. A cache keyed on the URL alone would hand the second
    caller the first one's board.

    Nothing in the chain caches this today (``api/jobs.ts`` edge-caches the
    ``facets`` sub-path only, and ``vercel.json`` sets no cache headers on
    ``/api/*``), so this is not a live leak and this test is not a regression
    guard for one. It is what stops the safety from resting entirely on a single
    ``if`` in a different repo layer — widening that ``if`` to cover ``search`` is
    the obvious performance change, and it is one line.

    The proxy sets its own copy for the same reason it re-emits ``X-Next-Cursor``
    by hand: ``forwardResponse`` copies status and body only, so these headers do
    not survive that hop. See ``jobs.serverless.test.ts`` for that half.
    """
    _insert_company(db_conn, "srch-pub6i", visibility="public")
    _insert_job(db_conn, "cache-1", "srch-pub6i", "greenhouse_api")

    resp = client.get("/api/jobs/search")
    assert resp.status_code == 200

    cache_control = resp.headers.get("cache-control", "")
    assert "no-store" in cache_control, f"got {cache_control!r}"
    assert "private" in cache_control, f"got {cache_control!r}"
    assert "Authorization" in resp.headers.get("vary", ""), (
        f"got {resp.headers.get('vary')!r}"
    )


# --- Leak 6c: ORPHANED custom jobs (company row deleted, job rows survive) ----
#
# THE INCIDENT THESE PIN, 2026-09-05. Every guard above works by FINDING the
# job's ``companies`` row and testing it. That shape fails OPEN when the row is
# absent: the anti-join's subquery matches nothing, ``NOT EXISTS`` is TRUE, and
# the job is served as public. There is no foreign key from
# ``job_listings.company`` to ``companies.id`` — a deliberate house convention,
# not an oversight — so the absent case is reachable.
#
# It was reached. ``scripts/one_off/purge_custom_companies.py`` deleted a company
# and its jobs while that company's ``fetch_custom_company`` job was already
# ``doing``. ``pending_jobs.cancel_queued_jobs`` cancels only ``todo`` jobs, by
# design, so the in-flight harvest was never stopped; it re-inserted 2,057 rows
# against the now-deleted company, and all 2,057 became readable by anonymous
# callers. The delete itself was not sloppy — every delete path funnels through
# ``purge_custom_company`` and removes the job rows in the same transaction. The
# orphans were created AFTER the delete committed.
#
# ``tasks/fetch_custom_company`` now re-checks the company row immediately before
# its upsert, which is the root-cause fix. These cases pin the SAFETY NET —
# ``database._ORPHANED_CUSTOM_PREDICATE`` — because the requirement is stronger
# than "the harvest behaves": NO orphan may ever be publicly visible, whatever
# created it. A future writer, a restored backup, a manual INSERT and a race the
# re-check loses are all covered here and none of them are covered there.
#
# Every case seeds the orphan the way production made it: insert the company,
# insert its jobs, then delete ONLY the company row and leave the jobs behind.


def _orphan(conn, company_id: str) -> None:
    """Delete the company row, leaving its ``job_listings`` rows orphaned.

    Exactly the production state after the 2026-09-05 purge raced the in-flight
    harvest: no ``companies`` row, no ``user_companies`` row, job rows intact.
    """
    cur = conn.cursor()
    cur.execute(
        sql.SQL("DELETE FROM {} WHERE company_id = %s").format(
            sql.Identifier("user_companies")
        ),
        (company_id,),
    )
    cur.execute(
        sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier("companies")),
        (company_id,),
    )
    conn.commit()


def test_orphaned_custom_job_is_not_in_the_anonymous_public_list(client, db_conn):
    """The headline case: 2,057 rows served to the world, in miniature."""
    _insert_company(db_conn, "pub-6c", visibility="public")
    _insert_company(db_conn, "u-orph6c0001", visibility="user")
    _insert_job(db_conn, "orph-6c-1", "pub-6c", "greenhouse_api")
    _insert_job(db_conn, "orph-6c-2", "u-orph6c0001", custom("u-orph6c0001"))
    _orphan(db_conn, "u-orph6c0001")

    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    ids = {j["id"] for j in resp.json()}
    assert "orph-6c-2" not in ids, (
        "an orphaned custom job was served to an anonymous caller — this is the "
        "2026-09-05 leak"
    )
    assert "orph-6c-1" in ids, "...without dropping the public corpus"

    # ...and it is still gone when the caller names the dead company explicitly.
    targeted = client.get("/api/jobs", params={"company": "u-orph6c0001"})
    assert targeted.status_code == 200
    assert targeted.json() == []


def test_orphaned_custom_job_detail_is_404(client, db_conn):
    _insert_company(db_conn, "u-orph6c0002", visibility="user")
    _insert_job(db_conn, "orph-6c-3", "u-orph6c0002", custom("u-orph6c0002"))
    _orphan(db_conn, "u-orph6c0002")

    resp = client.get(f"/api/jobs/{custom('u-orph6c0002')}/orph-6c-3")
    assert resp.status_code == 404


def test_orphaned_custom_job_is_not_in_another_users_search_feed(client, db_conn):
    """Another signed-in user must not see it — rows OR tiles.

    ``resp.text`` rather than the parsed id set because ``filteredTotal`` and
    ``countLast24h`` are computed by a SECOND composed WHERE
    (``job_search._header_counts_where``), and a guard applied to the rows query
    but not the tiles would leak the SIZE of a dead private board while showing
    none of it.
    """
    other_id = uuid.uuid4().hex
    other_email = f"{other_id}@example.com"
    _insert_user(db_conn, other_id, other_email)
    _insert_company(db_conn, "srch-pub6c", visibility="public")
    _insert_company(db_conn, "u-orph6c0003", visibility="user")
    _insert_job(db_conn, "orph-6c-4", "srch-pub6c", "greenhouse_api")
    _insert_job(db_conn, "orph-6c-5", "u-orph6c0003", custom("u-orph6c0003"))
    _orphan(db_conn, "u-orph6c0003")

    try:
        _login_optional_as(client, other_email)
        resp = client.get("/api/jobs/search")
        assert resp.status_code == 200
        ids = {j["id"] for j in resp.json()["jobs"]}
        assert "orph-6c-5" not in ids
        assert "orph-6c-5" not in resp.text, (
            "orphaned job leaked through the recency tiles / counts"
        )
        assert "orph-6c-4" in ids, "...without dropping the public corpus"
    finally:
        _logout_optional(client)


def test_orphaned_custom_job_is_hidden_even_from_its_former_owner(client, db_conn):
    """Fail CLOSED, including for the one caller with a claim to it.

    The orphan guard sits OUTSIDE the ownership ``OR`` in
    ``database._OWNED_USER_COMPANY_PREDICATE`` precisely so this holds. Inside
    the OR it would read "hide orphans unless you used to own them", which
    re-opens the hole for the caller most likely to still have the board in their
    feed. Once the company row is gone the board does not exist, and there is no
    ownership left to honour.
    """
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "srch-pub6c2", visibility="public")
    _insert_company(db_conn, "u-orph6c0004", visibility="user")
    _own(db_conn, owner_id, "u-orph6c0004")
    _insert_job(db_conn, "orph-6c-6", "srch-pub6c2", "greenhouse_api")
    _insert_job(db_conn, "orph-6c-7", "u-orph6c0004", custom("u-orph6c0004"))
    _orphan(db_conn, "u-orph6c0004")

    try:
        _login_optional_as(client, email)
        resp = client.get("/api/jobs/search")
        assert resp.status_code == 200
        ids = {j["id"] for j in resp.json()["jobs"]}
        assert "orph-6c-7" not in ids, (
            "the former owner still saw an orphaned board — the guard is inside "
            "the ownership OR instead of outside it"
        )
        assert "orph-6c-7" not in resp.text
        assert "orph-6c-6" in ids
    finally:
        _logout_optional(client)


def test_orphaned_custom_job_is_hidden_at_the_service_layer(db_conn):
    """The property where it is implemented, not where it is routed.

    Same reasoning as ``test_service_layer_read_paths_never_return_a_user_company_job``:
    this still fails if someone rewires the router or adds a second public reader.
    """
    _insert_company(db_conn, "svc-pub6c", visibility="public")
    _insert_company(db_conn, "u-orph6c0005", visibility="user")
    _insert_job(db_conn, "orph-6c-8", "svc-pub6c", "greenhouse_api")
    _insert_job(db_conn, "orph-6c-9", "u-orph6c0005", custom("u-orph6c0005"))
    _orphan(db_conn, "u-orph6c0005")

    companies = {j["company"] for j in get_jobs(db_conn)}
    assert "u-orph6c0005" not in companies
    assert "svc-pub6c" in companies

    assert get_jobs(db_conn, company="u-orph6c0005") == []
    assert get_job_by_id(db_conn, custom("u-orph6c0005"), "orph-6c-9") is None
    assert get_job_by_id(db_conn, "greenhouse_api", "orph-6c-8") is not None


def test_live_custom_board_is_still_visible_to_its_owner(client, db_conn):
    """CONTROL. The fix must not cost the owner their own live board.

    This is ``test_search_serves_the_owners_own_private_board_to_the_owner``
    restated next to the orphan cases, so a fix that hides orphans by hiding
    every ``custom:`` row fails HERE rather than shipping.
    """
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_company(db_conn, "u-live6c0001", visibility="user")
    _own(db_conn, owner_id, "u-live6c0001")
    _insert_job(db_conn, "live-6c-1", "u-live6c0001", custom("u-live6c0001"))

    try:
        _login_optional_as(client, email)
        resp = client.get("/api/jobs/search")
        assert resp.status_code == 200
        ids = {j["id"] for j in resp.json()["jobs"]}
        assert "live-6c-1" in ids, (
            "the orphan guard hid a LIVE custom board from its owner"
        )
    finally:
        _logout_optional(client)


def test_public_ats_jobs_are_unaffected_by_the_orphan_guard(client, db_conn):
    """CONTROL. Vendor-ATS rows never carry a recipe-engine prefix.

    The new conjunct must be a no-op for them — including when their company row
    is missing, which is the documented (and deliberate) fail-OPEN behaviour of
    the separate ``_HIDDEN_COMPANY_PREDICATE``. That is exactly why the orphan
    guard is scoped to the ``custom:``/``recipe:`` namespaces instead of hiding
    every row with no company: a blanket rule would have contradicted it.
    """
    _insert_company(db_conn, "pub-6c2", visibility="public")
    _insert_job(db_conn, "pub-6c-1", "pub-6c2", "greenhouse_api")
    _insert_job(db_conn, "pub-6c-2", "gone-co", "greenhouse_api")

    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    ids = {j["id"] for j in resp.json()}
    assert "pub-6c-1" in ids
    assert "pub-6c-2" in ids, (
        "a public-ATS job with no company row must stay visible — the orphan "
        "guard is scoped to the custom: namespace on purpose"
    )


# --- Leak 6d: the three orphan-guard claims Leak 6c asserts but does not test --
#
# Leak 6c is real and its headline cases are honest. These are the ones it
# MISSES, each found by reverting one piece of the guard and watching the whole
# file stay green.
#
#   1. the owner-scoped predicate  (guard moved INSIDE the ownership OR -> 33 passed)
#   2. the recency tiles           (guard dropped from _header_counts_where -> 139 passed)
#   3. GET /api/locations/search   (never carried the guard at all)
#
# All three are the same failure mode: a negative assertion that cannot fail,
# because the fixture never reaches the code the assertion names.


def _search_filters(**over):
    """A TOTAL :class:`job_search.SearchFilters` — it is deliberately not ``total=False``."""
    base = dict(
        status="OPEN", since=None, categories=None, levels=None, companies=None,
        locations=None, location_ids=None, include=None, exclude=None,
        owned_source_ids=None,
    )
    base.update(over)
    return base


def _insert_location(conn, canonical_name: str) -> int:
    """One canonical ``locations`` row; returns its id.

    ``city``/``region`` are filled from the name so each fixture satisfies
    ``uq_locations_canonical`` (kind, city, region, country, remote_scope).
    """
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (canonical_name, kind, city, region, country) "
            "VALUES (%s, 'city', %s, %s, 'US') RETURNING id"
        ).format(sql.Identifier("locations")),
        (canonical_name, canonical_name, canonical_name),
    )
    location_id = int(cur.fetchone()["id"])
    conn.commit()
    return location_id


def _tag_location(conn, job_id: str, location_id: int) -> None:
    """Give a job a normalized location. ``job_locations`` keys on the job id alone."""
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (job_listing_id, normalized_location_id, is_primary) "
            "VALUES (%s, %s, TRUE)"
        ).format(sql.Identifier("job_locations")),
        (job_id, location_id),
    )
    conn.commit()


def test_orphan_stays_hidden_when_the_owned_scope_itself_names_it(db_conn):
    """The orphan guard must sit OUTSIDE the ownership ``OR`` — and only this can tell.

    ``test_orphaned_custom_job_is_hidden_even_from_its_former_owner`` claims to
    pin that placement. It cannot. ``_orphan`` deletes the ``user_companies`` row
    as well, and ``custom_companies_service.list_owned_source_ids`` JOINs
    ``companies`` — so through the router an orphan's ``custom:`` id can never
    reach ``owned_source_ids``. The router takes the ``else`` branch, the case
    exercises the blanket ``_USER_COMPANY_PREDICATE``, and
    ``_OWNED_USER_COMPANY_PREDICATE`` is never evaluated at all. Confirmed by
    mutation: moving the guard inside the OR leaves this entire file green.

    So drive the owner-scoped predicate directly with the one input the router
    cannot build today — an owned set that NAMES the orphan. That is precisely
    the state a ``list_owned_source_ids`` without its JOIN, or a delete that
    drops ``companies`` while leaving ``user_companies``, would produce, and it
    is the state the placement argument in ``database.py`` is written about.
    """
    from api.services.job_search import search_jobs

    _insert_company(db_conn, "pub-6d", visibility="public")
    _insert_company(db_conn, "u-orph6d0001", visibility="user")
    _insert_job(db_conn, "orph-6d-1", "pub-6d", "greenhouse_api")
    _insert_job(db_conn, "orph-6d-2", "u-orph6d0001", custom("u-orph6d0001"))
    _orphan(db_conn, "u-orph6d0001")

    rows = search_jobs(
        db_conn, limit=50,
        **_search_filters(owned_source_ids=[custom("u-orph6d0001")]),
    )
    ids = {r["id"] for r in rows}
    assert "orph-6d-2" not in ids, (
        "an orphan NAMED BY the owned scope was served — the orphan guard is "
        "inside the ownership OR, where ownership can vote it back in"
    )
    assert "orph-6d-1" in ids, "...without dropping the public corpus"


def test_orphaned_custom_job_is_not_counted_in_the_recency_tiles(db_conn):
    """The tiles are separate SQL and need their own assertion, not ``resp.text``.

    ``test_orphaned_custom_job_is_not_in_another_users_search_feed`` asserts
    ``"orph-6c-5" not in resp.text`` and its docstring calls that the tile check.
    It is not one: the tiles return COUNTS and never ids, so a job id cannot
    appear in the tile payload however wrong the counts are. Confirmed by
    mutation: dropping the orphan guard from ``job_search._header_counts_where``
    leaves 139 tests green.

    The count IS the leak here — it publishes the SIZE of a deleted board.
    """
    from api.services.job_search import get_search_counts

    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _insert_company(db_conn, "pub-6d2", visibility="public")
    _insert_company(db_conn, "u-orph6d0002", visibility="user")
    _insert_job(db_conn, "orph-6d-3", "pub-6d2", "greenhouse_api", first_seen_at=fresh)
    _insert_job(
        db_conn, "orph-6d-4", "u-orph6d0002", custom("u-orph6d0002"),
        first_seen_at=fresh,
    )
    _orphan(db_conn, "u-orph6d0002")

    anon = get_search_counts(db_conn, **_search_filters())
    assert anon["count_last_24h"] == 1, (
        "the recency tile counted an orphaned custom job — the guard is on the "
        "rows query but not on _header_counts_where"
    )

    # ...and the OWNER-SCOPED form of the tile is guarded too, on the same input
    # the router cannot build (see the test above).
    owned = get_search_counts(
        db_conn, **_search_filters(owned_source_ids=[custom("u-orph6d0002")])
    )
    assert owned["count_last_24h"] == 1


def test_public_location_search_omits_private_and_orphaned_boards(db_conn):
    """``GET /api/locations/search?openOnly=true`` is a PUBLIC read over job_listings.

    Unauthenticated, allow-listed through ``api/locations.ts``, edge-cached for
    ten minutes — and its ``EXISTS`` over ``job_listings`` carried NEITHER guard.
    That makes it an EXISTENCE ORACLE: a canonical location enters the world's
    dropdown because someone's private board, or an orphaned ``custom:`` row, has
    an OPEN job there. It returns no job row, which is exactly why it was missed
    — the leak is the FACT of the row, not its contents.

    Three boards, three locations, one visible answer.
    """
    from api.services.saved_filters_service import search_locations

    pub_loc = _insert_location(db_conn, "Publictown, ZZ")
    priv_loc = _insert_location(db_conn, "Privateton, ZZ")
    orph_loc = _insert_location(db_conn, "Orphanhaven, ZZ")

    _insert_company(db_conn, "pub-6d3", visibility="public")
    _insert_company(db_conn, "u-priv6d0003", visibility="user")
    _insert_company(db_conn, "u-orph6d0003", visibility="user")

    _insert_job(db_conn, "loc-6d-1", "pub-6d3", "greenhouse_api")
    _insert_job(db_conn, "loc-6d-2", "u-priv6d0003", custom("u-priv6d0003"))
    _insert_job(db_conn, "loc-6d-3", "u-orph6d0003", custom("u-orph6d0003"))

    _tag_location(db_conn, "loc-6d-1", pub_loc)
    _tag_location(db_conn, "loc-6d-2", priv_loc)
    _tag_location(db_conn, "loc-6d-3", orph_loc)

    _orphan(db_conn, "u-orph6d0003")

    names = {
        r["canonical_name"]
        for r in search_locations(db_conn, "ZZ", limit=50, open_only=True)
    }
    assert "Publictown, ZZ" in names, "the public corpus must still populate the filter"
    assert "Privateton, ZZ" not in names, (
        "a location entered the PUBLIC dropdown because a PRIVATE board has an "
        "open job there — an existence oracle over someone else's board"
    )
    assert "Orphanhaven, ZZ" not in names, (
        "same leak via an ORPHANED custom row — the 2026-09-05 shape"
    )


def test_public_location_search_omits_deactivated_companies(db_conn):
    """The other half of "the same corpus as ``/api/jobs``".

    Consistency rather than secrecy: ``/api/jobs`` drops a soft-deactivated
    company's rows, so without ``_HIDDEN_COMPANY_PREDICATE`` here the dropdown
    offers a location that matches zero jobs. Pinned so the two predicate sets
    cannot drift apart again.
    """
    from api.services.saved_filters_service import search_locations

    live = _insert_location(db_conn, "Liveville, YY")
    dead = _insert_location(db_conn, "Deadwood, YY")
    _insert_company(db_conn, "pub-6d4", visibility="public")
    _insert_company(db_conn, "dead-6d4", visibility="public", enabled=False)
    _insert_job(db_conn, "loc-6d-4", "pub-6d4", "greenhouse_api")
    _insert_job(db_conn, "loc-6d-5", "dead-6d4", "greenhouse_api")
    _tag_location(db_conn, "loc-6d-4", live)
    _tag_location(db_conn, "loc-6d-5", dead)

    names = {
        r["canonical_name"]
        for r in search_locations(db_conn, "YY", limit=50, open_only=True)
    }
    assert "Liveville, YY" in names
    assert "Deadwood, YY" not in names


def test_location_search_without_open_only_is_untouched(db_conn):
    """CONTROL. The unfiltered branch reads ``locations`` alone and must not change.

    It never joins ``job_listings``, so it has nothing to leak and nothing to
    guard — and a fix that "hardened" it by requiring an open job would silently
    change what the dropdown offers to a caller who asked for everything.
    """
    from api.services.saved_filters_service import search_locations

    _insert_location(db_conn, "Nojobsburg, XX")
    names = {
        r["canonical_name"]
        for r in search_locations(db_conn, "XX", limit=50, open_only=False)
    }
    assert "Nojobsburg, XX" in names


# --- Leak 6e: a STRANDED PUBLISHED recipe corpus -------------------------------
#
# The orphan guard of Leak 6c short-circuited on ``NOT starts_with(source_id,
# 'custom:')``, on the stated premise that the ``custom:`` prefix "can only ever be
# private". The published recipe boards (``companies.ats='recipe'``) broke that premise
# without touching it: their rows carry ``recipe:<id>``, a namespace the guard did not
# name, so a ``recipe:`` row whose ``companies`` row is gone fell straight through to
# the fail-OPEN anti-join and was served.
#
# NOT hypothetical, and not even exotic. The seed migration that publishes these four
# boards (``4c1f8a26d7be``) deletes the four ``companies`` rows on ``downgrade()`` — one
# ``alembic downgrade`` away from ~3,000 stranded ``recipe:oracle`` / ``recipe:dell``
# rows. They disappear from ``GET /api/jobs`` because it INNER JOINs ``companies``,
# which is exactly what makes the hole quiet: the obvious surface looks clean while
# ``GET /api/jobs/search`` (no join) keeps serving a board nobody is scraping any more.
# The migration now deletes those job rows in the same transaction; these cases pin the
# read-side backstop, which has to hold whatever created the state.
#
# Note the shape difference from 6c and why both matter: a stranded ``recipe:`` corpus
# is not a privacy leak (the board WAS public) — it is a TRUTHFULNESS leak. The rows say
# OPEN and nothing will ever close them.


def _seed_recipe_board(conn, company_id: str, job_id: str) -> None:
    """A published recipe board with one job row, in the ``recipe:`` namespace."""
    _insert_company(conn, company_id, visibility="public", ats=RECIPE_ATS)
    _insert_job(conn, job_id, company_id, recipe(company_id))


def _strand(conn, company_id: str) -> None:
    """Delete ONLY the ``companies`` row — what ``downgrade()`` used to leave behind."""
    cur = conn.cursor()
    cur.execute(
        sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier("companies")),
        (company_id,),
    )
    conn.commit()


def test_stranded_recipe_job_is_not_served_on_the_public_search_feed(client, db_conn):
    """THE case: ``/api/jobs/search`` does not join ``companies``, so nothing else stops it."""
    _insert_company(db_conn, "pub-6e", visibility="public")
    _insert_job(db_conn, "strand-6e-1", "pub-6e", "greenhouse_api")
    _seed_recipe_board(db_conn, "oracle6e", "strand-6e-2")
    _strand(db_conn, "oracle6e")

    resp = client.get("/api/jobs/search")
    assert resp.status_code == 200
    ids = {j["id"] for j in resp.json()["jobs"]}
    assert "strand-6e-2" not in ids, (
        "a stranded PUBLISHED recipe job was served — the orphan guard only names "
        "the custom: prefix"
    )
    assert "strand-6e-2" not in resp.text, "...including through the recency tiles"
    assert "strand-6e-1" in ids, "...without dropping the public corpus"


def test_stranded_recipe_job_is_hidden_at_the_service_layer(db_conn):
    """The property where it is implemented, not where it is routed."""
    _insert_company(db_conn, "pub-6e2", visibility="public")
    _insert_job(db_conn, "strand-6e-3", "pub-6e2", "greenhouse_api")
    _seed_recipe_board(db_conn, "dell6e", "strand-6e-4")
    _strand(db_conn, "dell6e")

    companies = {j["company"] for j in get_jobs(db_conn)}
    assert "dell6e" not in companies
    assert "pub-6e2" in companies
    assert get_jobs(db_conn, company="dell6e") == []
    assert get_job_by_id(db_conn, recipe("dell6e"), "strand-6e-4") is None
    assert get_job_by_id(db_conn, "greenhouse_api", "strand-6e-3") is not None


def test_stranded_recipe_job_is_not_counted_in_the_recency_tiles(db_conn):
    """The tiles are separate SQL (``job_search._header_counts_where``) and the count
    is the leak: it publishes the SIZE of a board that no longer exists."""
    from api.services.job_search import get_search_counts

    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _insert_company(db_conn, "pub-6e3", visibility="public")
    _insert_job(db_conn, "strand-6e-5", "pub-6e3", "greenhouse_api", first_seen_at=fresh)
    _insert_company(db_conn, "github6e", visibility="public", ats=RECIPE_ATS)
    _insert_job(
        db_conn, "strand-6e-6", "github6e", recipe("github6e"), first_seen_at=fresh
    )
    _strand(db_conn, "github6e")

    counts = get_search_counts(db_conn, **_search_filters())
    assert counts["count_last_24h"] == 1, (
        "the recency tile counted a stranded recipe job — the guard is on the rows "
        "query but not on _header_counts_where"
    )


def test_public_location_search_omits_stranded_recipe_boards(db_conn):
    """The existence oracle, for the published namespace too."""
    from api.services.saved_filters_service import search_locations

    live = _insert_location(db_conn, "Recipeville, WW")
    dead = _insert_location(db_conn, "Strandtown, WW")
    _insert_company(db_conn, "pub-6e4", visibility="public")
    _insert_job(db_conn, "loc-6e-1", "pub-6e4", "greenhouse_api")
    _seed_recipe_board(db_conn, "atlassian6e", "loc-6e-2")
    _tag_location(db_conn, "loc-6e-1", live)
    _tag_location(db_conn, "loc-6e-2", dead)
    _strand(db_conn, "atlassian6e")

    names = {
        r["canonical_name"]
        for r in search_locations(db_conn, "WW", limit=50, open_only=True)
    }
    assert "Recipeville, WW" in names
    assert "Strandtown, WW" not in names


def test_a_LIVE_published_recipe_board_is_still_public(client, db_conn):
    """CONTROL, and the one that matters most — these boards are meant to be visible.

    A fix that hid orphans by hiding every ``recipe:`` row would dark the four boards
    this branch exists to publish, on both public readers. It fails HERE.
    """
    _seed_recipe_board(db_conn, "atlassian6f", "live-6e-1")

    listed = client.get("/api/jobs")
    assert listed.status_code == 200
    assert "live-6e-1" in {j["id"] for j in listed.json()}

    searched = client.get("/api/jobs/search")
    assert searched.status_code == 200
    assert "live-6e-1" in {j["id"] for j in searched.json()["jobs"]}

    assert get_job_by_id(db_conn, recipe("atlassian6f"), "live-6e-1") is not None


def test_the_orphan_guard_names_every_recipe_engine_namespace():
    """ANTI-DRIFT. The guard is a hand-written SQL literal, so a THIRD namespace added
    to ``scripts.shared.constants`` would be outside it and nothing else would notice —
    which is precisely how ``recipe:`` got out. Derived from the constants, so this
    cannot be satisfied by editing the expected list.
    """
    from api.services.database import _ORPHANED_CUSTOM_PREDICATE

    predicate = _ORPHANED_CUSTOM_PREDICATE.as_string(None)
    for prefix in (CUSTOM_SOURCE_PREFIX, RECIPE_SOURCE_PREFIX):
        assert f"'{prefix}'" in predicate, (
            f"the orphan guard does not name the {prefix!r} namespace — rows in it "
            f"are served as public when their companies row goes missing"
        )
