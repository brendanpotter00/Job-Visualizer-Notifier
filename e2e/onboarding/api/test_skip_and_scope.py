"""OB-05 / OB-06 / OB-07 — what a Skip keeps, where a specialty may go, and
what an existing saved-filters row keeps.
"""

from __future__ import annotations

from conftest import (
    KEYWORD_LISTS,
    ONBOARDING,
    SAVED_FILTERS,
    USERS,
    api_lists,
    dump_json,
    fixtures,
    identities,
    ok_json,
    saved_lists,
)
from e2e.onboarding.fixtures import Answers

EMPTY = {"category": [], "subcategory": [], "level": [], "locations": []}


def test_ob05_skip_keeps_the_answers_already_given(identity, conn):
    """Decision `keep`: Skip on question 2 after picking a level saves that
    level. A Skip that threw it away would make Skip and Finish disagree about
    what the user said."""
    me = identity("OB-05")
    body = ok_json(
        me.post(ONBOARDING, Answers(level=["senior"]).body(skipped=True, step=2)),
        "POST /api/users/onboarding (skip with a level)",
    )
    assert body["onboardingCompletedAt"], "a Skip did not stamp the account — the flow never ends"
    expected = {**EMPTY, "level": ["senior"]}
    assert api_lists(body["savedFilters"]) == expected, (
        f"Skip saved {api_lists(body['savedFilters'])}, expected the level it was given {expected}"
    )
    row = identities.user_row(conn, me.ident)
    assert row is not None and row["onboarding_completed_at"] is not None
    sf = identities.saved_filters_row(conn, row["id"])
    assert sf is not None and saved_lists(sf) == expected, (
        f"user_saved_filters holds {sf and saved_lists(sf)}, expected {expected}"
    )


def test_ob05_skip_with_no_answers_still_ends_the_flow(identity, conn):
    me = identity("OB-05-empty")
    body = ok_json(
        me.post(ONBOARDING, Answers().body(skipped=True, step=1)),
        "POST /api/users/onboarding (skip with nothing)",
    )
    assert body["onboardingCompletedAt"], (
        "an empty Skip did not stamp the account — the questions would come back on every visit"
    )
    assert api_lists(body["savedFilters"]) == EMPTY
    row = identities.user_row(conn, me.ident)
    assert row is not None and row["onboarding_completed_at"] is not None, (
        "an empty Skip answered 200 but left users.onboarding_completed_at NULL"
    )
    # Signing in again reads the stamp back.
    again = ok_json(me.get(USERS), "GET /api/users (after an empty skip)")
    assert again["onboardingCompletedAt"] == body["onboardingCompletedAt"]
    sf = identities.saved_filters_row(conn, row["id"])
    if sf is not None:
        assert saved_lists(sf) == EMPTY, f"an empty Skip saved answers it was never given: {saved_lists(sf)}"


def test_ob06_a_specialty_is_saved_only_with_software_engineering(identity, conn, case_dir):
    """A specialty refines Software Engineering. Saved beside another role
    alone it would be an orphan the search then scopes oddly, so the server
    drops it. The MIRROR — the same specialty beside SWE AND that role — is
    kept, which proves the drop is about the missing parent and not about the
    pair."""
    orphan = identity("OB-06")
    body = ok_json(
        orphan.post(
            ONBOARDING,
            Answers(category=[fixtures.PM], subcategory=["backend"]).body(skipped=False, step=3),
        ),
        "POST (product_manager + backend)",
    )
    dump_json(case_dir / "orphan.json", body)
    assert body["savedFilters"]["category"] == [fixtures.PM]
    assert body["savedFilters"]["subcategory"] == [], (
        f"a specialty without Software Engineering was saved: {body['savedFilters']['subcategory']}"
    )
    row = identities.user_row(conn, orphan.ident)
    assert row is not None
    sf = identities.saved_filters_row(conn, row["id"])
    assert sf is not None and sf["subcategory"] == [] and sf["category"] == [fixtures.PM]

    mirror = identity("OB-06-mirror")
    body = ok_json(
        mirror.post(
            ONBOARDING,
            Answers(category=[fixtures.SWE, fixtures.PM], subcategory=["backend"]).body(
                skipped=False, step=3
            ),
        ),
        "POST (software_engineering + product_manager + backend)",
    )
    assert body["savedFilters"]["subcategory"] == ["backend"], (
        "the specialty was dropped even WITH Software Engineering picked — the rule is "
        f"over-eager: saved {body['savedFilters']}"
    )
    assert body["savedFilters"]["category"] == [fixtures.SWE, fixtures.PM]


def test_ob07_an_existing_saved_filters_row_keeps_what_onboarding_does_not_set(identity, conn, case_dir):
    """Onboarding writes FOUR columns. Everything else on an existing row —
    both time windows and both keyword-list pointers — must survive it."""
    me = identity("OB-07")
    ok_json(me.get(USERS), "GET /api/users (creates the row the saved-filters API needs)")

    created = me.post(KEYWORD_LISTS, {"name": "E2E onboarding list", "tags": [{"text": "python", "mode": "include"}]})
    assert created.status_code in (200, 201), (
        f"POST keyword-lists answered {created.status_code}: {created.text[:300]}"
    )
    list_id = created.json()["id"]

    before = {
        "recentTimeWindow": "7d",
        "trendTimeWindow": "30d",
        "locations": [fixtures.NEW_YORK],
        "category": ["growth"],
        "level": ["mid"],
        "subcategory": [],
        "recentActiveKeywordListId": list_id,
        "trendActiveKeywordListId": "builtin-swe",
    }
    put = ok_json(me.put(SAVED_FILTERS, before), "PUT /api/users/saved-filters (pre-existing row)")
    assert put["recentTimeWindow"] == "7d" and put["recentActiveKeywordListId"] == list_id

    body = ok_json(
        me.post(ONBOARDING, fixtures.HEADLINE.body(skipped=False, step=3)),
        "POST /api/users/onboarding over an existing row",
    )
    dump_json(case_dir / "onboarding.json", body)
    saved = body["savedFilters"]
    assert api_lists(saved) == fixtures.HEADLINE.as_saved(), (
        f"onboarding did not replace the four answer columns: {api_lists(saved)}"
    )
    kept = {
        k: saved[k]
        for k in ("recentTimeWindow", "trendTimeWindow", "recentActiveKeywordListId", "trendActiveKeywordListId")
    }
    assert kept == {
        "recentTimeWindow": "7d",
        "trendTimeWindow": "30d",
        "recentActiveKeywordListId": list_id,
        "trendActiveKeywordListId": "builtin-swe",
    }, f"onboarding overwrote settings it does not own: {kept}"

    row = identities.user_row(conn, me.ident)
    assert row is not None
    sf = identities.saved_filters_row(conn, row["id"])
    assert sf is not None
    assert saved_lists(sf) == fixtures.HEADLINE.as_saved()
    assert (sf["recent_time_window"], sf["trend_time_window"]) == ("7d", "30d"), (
        f"the time windows were reset to ({sf['recent_time_window']}, {sf['trend_time_window']}) — "
        "the upsert replaced the whole row"
    )
    assert sf["recent_active_keyword_list_id"] == list_id
    assert sf["trend_active_keyword_list_id"] == "builtin-swe"
