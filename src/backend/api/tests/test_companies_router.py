"""Integration tests for the curated-companies router (GET /api/companies)."""

from unittest.mock import patch

import psycopg2
from psycopg2 import sql


def _insert_company(
    db_conn, company_id, display_name, ats="greenhouse", blurb=None, accomplishment=None, enabled=True
):
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, blurb, accomplishment)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, display_name, ats, company_id, enabled, blurb, accomplishment),
    )
    db_conn.commit()


def test_returns_empty_list_when_no_companies(client, db_conn):
    resp = client.get("/api/companies")
    assert resp.status_code == 200
    assert resp.json() == {"companies": []}


def test_returns_companies_sorted_alphabetically_case_insensitive(client, db_conn):
    _insert_company(db_conn, "zoox", "Zoox", "lever")
    _insert_company(db_conn, "airbnb", "Airbnb", "greenhouse")
    _insert_company(db_conn, "fal", "fal", "greenhouse")  # lowercase display name

    data = client.get("/api/companies").json()
    names = [c["displayName"] for c in data["companies"]]
    # case-insensitive: 'fal' sorts between Airbnb and Zoox, not last
    assert names == ["Airbnb", "fal", "Zoox"]


def test_camelcase_keys_and_fields(client, db_conn):
    _insert_company(
        db_conn, "stripe", "Stripe", "greenhouse",
        blurb="Payments infra.", accomplishment="Powers checkout.",
    )
    company = client.get("/api/companies").json()["companies"][0]
    assert company == {
        "id": "stripe",
        "displayName": "Stripe",
        "ats": "greenhouse",
        "blurb": "Payments infra.",
        "accomplishment": "Powers checkout.",
    }


def test_null_blurb_and_accomplishment_serialize_as_null(client, db_conn):
    _insert_company(db_conn, "newco", "New Co", "ashby")  # no blurb/accomplishment
    company = client.get("/api/companies").json()["companies"][0]
    assert company["blurb"] is None
    assert company["accomplishment"] is None


def test_excludes_disabled_companies(client, db_conn):
    _insert_company(db_conn, "active", "Active Co", "greenhouse", enabled=True)
    _insert_company(db_conn, "retired", "Retired Co", "greenhouse", enabled=False)

    ids = [c["id"] for c in client.get("/api/companies").json()["companies"]]
    assert ids == ["active"]


def test_script_company_is_listed(client, db_conn):
    # Google/Apple/Microsoft live in the directory under the sentinel ats.
    _insert_company(db_conn, "google", "Google", "script", blurb="Search.")
    ids = [c["id"] for c in client.get("/api/companies").json()["companies"]]
    assert "google" in ids


def test_db_error_returns_500(client, db_conn):
    with patch(
        "api.routers.companies.list_enabled_companies_with_profiles",
        side_effect=psycopg2.OperationalError("boom"),
    ):
        resp = client.get("/api/companies")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to list companies"
