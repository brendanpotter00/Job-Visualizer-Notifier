"""E7 §5 — the three private-company visibility leaks + the fan-out gate.

A ``visibility='user'`` company must be invisible on every UNAUTHENTICATED or
cross-user surface:
  1. the public curated directory ``GET /api/companies``,
  2. the public ``GET /api/jobs`` list AND single-job detail,
  3. the auto-enroll UNION (never pulled into another user's feed), and
  4. the six ATS fan-outs (``list_enabled_companies(conn, ats)``).
"""

from __future__ import annotations

import uuid

from psycopg2 import sql

from scripts.shared.constants import custom
from scripts.shared.database import (
    list_enabled_companies as list_ats_enabled_companies,
)
from api.services.user_preferences_service import (
    list_enabled_companies as list_user_enabled_companies,
)


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
