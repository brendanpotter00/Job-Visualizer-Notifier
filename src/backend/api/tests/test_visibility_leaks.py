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
"""

from __future__ import annotations

import uuid

import pytest
from psycopg2 import sql

from scripts.shared.constants import custom
from api.auth.dependencies import get_current_user
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


def _insert_job(conn, job_id: str, company: str, source_id: str, *, status: str = "OPEN") -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("job_listings")),
        (
            job_id, "Engineer", company, "https://x/1", source_id,
            "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", status,
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
