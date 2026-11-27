"""``GET /api/jobs/search?company_category=`` — the Recent page's "Company type" filter.

The server resolves the category slugs to member company ids
(``company_category_members``), then filters with ``job_listings.company =
ANY(...)``. The failures worth guarding are silent ones:

- a dropped param or predicate returns an unfiltered 200 (so every case has a
  non-member decoy that must NOT come back);
- a truthiness check on the resolved ids turns "no members" into "all jobs"
  (so unknown slugs and empty categories must return zero rows);
- a cursor that survives a filter or membership change walks two sets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from psycopg2 import sql

from api.auth.dependencies import get_optional_user_lenient
from api.pagination import compute_filter_fingerprint
from api.services.company_categories import CompanyCategoryDef, seed_company_categories
from scripts.shared.constants import custom

from .conftest import _insert_job, _make_job
from .test_jobs_search_contract import _fingerprint_of

SEARCH = "/api/jobs/search"
BASE_TIME = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

CATEGORIES = {
    "big_tech": ["google", "apple"],
    "fintech": ["stripe", "ramp"],
    "empty_cat": [],
}


def _seed_categories(conn, categories: dict[str, list[str]] = CATEGORIES) -> None:
    defs: list[CompanyCategoryDef] = [
        {
            "slug": slug,
            "label": slug.replace("_", " ").title(),
            "definition": f"Members of {slug}.",
            "company_ids": list(ids),
        }
        for slug, ids in categories.items()
    ]
    seed_company_categories(conn, defs)


def _seed(conn, job_id: str, company: str, *, minutes_before: int = 0,
          first_seen_at: datetime | None = None, **overrides) -> str:
    moment = first_seen_at or (BASE_TIME - timedelta(minutes=minutes_before))
    _insert_job(conn, _make_job({
        "id": job_id,
        "company": company,
        "first_seen_at": moment.isoformat(),
        "last_seen_at": moment.isoformat(),
        **overrides,
    }))
    return job_id


def _search(client, **params) -> dict:
    resp = client.get(SEARCH, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(body: dict) -> set[str]:
    return {job["id"] for job in body["jobs"]}


def _corpus(conn) -> None:
    _seed(conn, "g1", "google", minutes_before=0)
    _seed(conn, "a1", "apple", minutes_before=1)
    _seed(conn, "s1", "stripe", minutes_before=2)
    _seed(conn, "decoy", "acme", minutes_before=3)  # in no category


# ---------------------------------------------------------------------------
# Membership semantics
# ---------------------------------------------------------------------------


def test_one_type_returns_only_member_companies(client, db_conn):
    _seed_categories(db_conn)
    _corpus(db_conn)

    assert _ids(_search(client)) == {"g1", "a1", "s1", "decoy"}  # control
    assert _ids(_search(client, company_category="big_tech")) == {"g1", "a1"}


def test_two_types_or_together(client, db_conn):
    _seed_categories(db_conn)
    _corpus(db_conn)

    body = _search(client, company_category=["big_tech", "fintech"])

    assert _ids(body) == {"g1", "a1", "s1"}


def test_a_company_in_two_selected_types_appears_once(client, db_conn):
    _seed_categories(db_conn, {"big_tech": ["google"], "ai_labs": ["google"]})
    _seed(db_conn, "g1", "google")

    body = _search(client, company_category=["big_tech", "ai_labs"])

    assert [job["id"] for job in body["jobs"]] == ["g1"]


def test_ands_with_the_company_filter(client, db_conn):
    """``company`` is the reader's followed boards; the type narrows inside it."""
    _seed_categories(db_conn)
    _corpus(db_conn)

    body = _search(client, company=["google", "stripe"], company_category="big_tech")

    assert _ids(body) == {"g1"}


def test_ands_with_category_and_level(client, db_conn, seed_taxonomy):
    _seed_categories(db_conn)
    _seed(db_conn, "want", "google", minutes_before=0,
          enrichment_category="software_engineering", enrichment_level="senior")
    _seed(db_conn, "wrong-level", "google", minutes_before=1,
          enrichment_category="software_engineering", enrichment_level="entry")
    _seed(db_conn, "wrong-category", "apple", minutes_before=2,
          enrichment_category="data_scientist", enrichment_level="senior")
    _seed(db_conn, "non-member", "stripe", minutes_before=3,
          enrichment_category="software_engineering", enrichment_level="senior")

    body = _search(
        client,
        company_category="big_tech",
        category="software_engineering",
        level="senior",
    )

    assert _ids(body) == {"want"}


def test_an_unknown_slug_matches_nothing(client, db_conn):
    """Well-formed but unknown: an empty result, not an error and not everything."""
    _seed_categories(db_conn)
    _corpus(db_conn)

    assert _search(client, company_category="quantum_alchemy")["jobs"] == []


def test_a_category_with_no_members_matches_nothing(client, db_conn):
    """The resolved id list is ``[]``. The predicate must still apply."""
    _seed_categories(db_conn)
    _corpus(db_conn)

    assert _search(client, company_category="empty_cat")["jobs"] == []


def test_an_unseeded_db_matches_nothing_rather_than_everything(client, db_conn):
    """Migrated, not yet seeded (or a failed seed): no member rows at all."""
    _corpus(db_conn)

    assert _search(client, company_category="big_tech")["jobs"] == []


def test_build_search_where_treats_empty_ids_as_an_active_filter():
    """Pins ``is not None``: ``[]`` emits the clause, ``None`` does not."""
    from api.services.job_search import build_search_where

    none_sql, none_params = build_search_where(status="OPEN", company_category_ids=None)
    empty_sql, empty_params = build_search_where(status="OPEN", company_category_ids=[])

    assert [] not in none_params
    assert [] in empty_params
    assert len(empty_params) == len(none_params) + 1
    assert none_sql != empty_sql


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_malformed_slug_is_422(client, db_conn):
    for bad in ["Big-Tech", "big tech", "big_tech\n", "x" * 41]:
        resp = client.get(SEARCH, params={"company_category": bad})
        assert resp.status_code == 422, (bad, resp.text)
        assert "company_category" in resp.json()["detail"]


def test_more_than_twenty_values_is_400(client, db_conn):
    values = [f"type_{chr(97 + i)}" for i in range(21)]

    resp = client.get(SEARCH, params={"company_category": values})

    assert resp.status_code == 400, resp.text
    assert "company_category" in resp.json()["detail"]


def test_twenty_values_is_fine(client, db_conn):
    values = [f"type_{chr(97 + i)}" for i in range(20)]

    resp = client.get(SEARCH, params={"company_category": values})

    assert resp.status_code == 200, resp.text


def test_duplicate_values_are_deduped(client, db_conn):
    """A repeated slug means the same query, so its cursor works for the single form."""
    _seed_categories(db_conn)
    _corpus(db_conn)

    first = _search(client, company_category=["big_tech", "big_tech"], limit=1)
    assert first["nextCursor"]

    page2 = client.get(
        SEARCH,
        params={"company_category": "big_tech", "limit": 1, "cursor": first["nextCursor"]},
    )
    assert page2.status_code == 200, page2.text


# ---------------------------------------------------------------------------
# Keyset paging + cursor fingerprint
# ---------------------------------------------------------------------------


def test_a_three_page_walk_is_complete_and_ordered(client, db_conn):
    _seed_categories(db_conn)
    members = []
    for i in range(7):
        company = "google" if i % 2 == 0 else "stripe"
        members.append(_seed(db_conn, f"m{i}", company, minutes_before=i * 2))
        _seed(db_conn, f"d{i}", "acme", minutes_before=i * 2 + 1)  # interleaved decoys

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"company_category": ["big_tech", "fintech"], "limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = _search(client, **params)
        pages += 1
        seen.extend(job["id"] for job in body["jobs"])
        cursor = body["nextCursor"]
        if not cursor:
            break
        assert pages < 10, "walk did not terminate"

    assert pages == 3
    assert seen == members  # newest first, no gaps, no duplicates, no decoys


def test_a_cursor_minted_without_the_param_keeps_its_fingerprint(client, db_conn):
    """Absent param = the pre-change fingerprint input, so in-flight cursors
    stay valid on deploy day."""
    _corpus(db_conn)

    _seed(db_conn, "g2", "google", minutes_before=10)
    first = _search(client, company="google", limit=1)
    assert first["nextCursor"]

    pre_change_inputs = {
        "status": "OPEN",
        "since": None,
        "category": [],
        "level": [],
        "company": ["google"],
        "location": [],
        "location_resolved": [],
        "location_ids": [],
        "include": [],
        "exclude": [],
        "owned_sources": [],
    }
    assert _fingerprint_of(first["nextCursor"]) == compute_filter_fingerprint(
        pre_change_inputs
    )
    page2 = client.get(
        SEARCH, params={"company": "google", "limit": 1, "cursor": first["nextCursor"]}
    )
    assert page2.status_code == 200, page2.text


def test_changing_the_filter_mid_walk_is_409(client, db_conn):
    _seed_categories(db_conn)
    _seed(db_conn, "g1", "google", minutes_before=0)
    _seed(db_conn, "a1", "apple", minutes_before=1)
    _seed(db_conn, "s1", "stripe", minutes_before=2)
    _seed(db_conn, "r1", "ramp", minutes_before=3)

    with_type = _search(client, company_category="big_tech", limit=1)["nextCursor"]
    without = _search(client, limit=1)["nextCursor"]
    assert with_type and without

    for params in (
        {"company_category": "fintech", "cursor": with_type},   # changed type
        {"cursor": with_type},                                  # filter removed
        {"company_category": "big_tech", "cursor": without},    # filter added
    ):
        resp = client.get(SEARCH, params={"limit": 1, **params})
        assert resp.status_code == 409, (params, resp.text)

    # Control: the same filter replays fine.
    ok = client.get(SEARCH, params={"company_category": "big_tech", "limit": 1,
                                    "cursor": with_type})
    assert ok.status_code == 200, ok.text


def test_a_membership_change_mid_walk_is_409(client, db_conn):
    """A reseed on deploy can move a company in or out. The resolved ids are in
    the fingerprint, so the walk restarts instead of mixing two sets."""
    _seed_categories(db_conn)
    _seed(db_conn, "g1", "google", minutes_before=0)
    _seed(db_conn, "a1", "apple", minutes_before=1)
    _seed(db_conn, "s1", "stripe", minutes_before=2)

    cursor = _search(client, company_category="big_tech", limit=1)["nextCursor"]
    assert cursor

    _seed_categories(db_conn, {**CATEGORIES, "big_tech": ["google", "apple", "stripe"]})

    resp = client.get(SEARCH, params={"company_category": "big_tech", "limit": 1,
                                      "cursor": cursor})
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# Recency tiles + private boards
# ---------------------------------------------------------------------------


def test_recency_tiles_ignore_the_company_type(client, db_conn):
    """The tiles answer "how busy are the boards I follow", like category/level."""
    _seed_categories(db_conn)
    fresh = datetime.now(timezone.utc) - timedelta(hours=1)
    _seed(db_conn, "g1", "google", first_seen_at=fresh)
    _seed(db_conn, "s1", "stripe", first_seen_at=fresh - timedelta(minutes=1))
    _seed(db_conn, "decoy", "acme", first_seen_at=fresh - timedelta(minutes=2))

    plain = _search(client)["meta"]
    filtered_body = _search(client, company_category="big_tech")
    filtered = filtered_body["meta"]

    assert _ids(filtered_body) == {"g1"}
    assert plain["countLast24h"] == 3
    assert filtered["countLast24h"] == plain["countLast24h"]
    assert filtered["countLast3h"] == plain["countLast3h"]


def _insert_user(conn, user_id: str, email: str) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())"
        ).format(sql.Identifier("users")),
        (user_id, f"auth0|{user_id}", email),
    )
    conn.commit()


def _insert_private_board(conn, owner_id: str, company_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES (%s, %s, 'greenhouse', %s, TRUE, 'user')"
        ).format(sql.Identifier("companies")),
        (company_id, company_id, company_id),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) VALUES (%s, %s, %s)"
        ).format(sql.Identifier("user_companies")),
        (owner_id, company_id, f"greenhouse:{company_id}"),
    )
    conn.commit()


def test_an_active_filter_hides_the_owners_private_board(client, db_conn):
    """Private boards are in no category. The owner sees them unfiltered
    (control) and not while a company type is active."""
    _seed_categories(db_conn)
    owner_id = uuid.uuid4().hex
    email = f"{owner_id}@example.com"
    _insert_user(db_conn, owner_id, email)
    _insert_private_board(db_conn, owner_id, "u-cc000001")
    _seed(db_conn, "g1", "google", minutes_before=0)
    _seed(db_conn, "private", "u-cc000001", minutes_before=1,
          source_id=custom("u-cc000001"))

    client.app.dependency_overrides[get_optional_user_lenient] = lambda: {
        "sub": f"auth0|{owner_id}", "email": email,
        "given_name": "A", "family_name": "B", "picture": None,
    }
    try:
        assert _ids(_search(client)) == {"g1", "private"}
        assert _ids(_search(client, company_category="big_tech")) == {"g1"}
    finally:
        client.app.dependency_overrides.pop(get_optional_user_lenient, None)
