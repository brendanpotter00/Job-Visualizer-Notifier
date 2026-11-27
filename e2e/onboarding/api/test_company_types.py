"""OB-10 — question 4, company types, through `POST /api/users/onboarding`.

The answer is saved as `user_saved_filters.company_category` (the Recent
page's Company type filter). Like the saved-filters PUT, an OMITTED key keeps
the stored value: that is what an SPA built before question 4 sends, so it
can never wipe a stored answer. `step` goes up to 4 now, and 5 is refused.
"""

from __future__ import annotations

from conftest import (
    ONBOARDING,
    SAVED_FILTERS,
    USERS,
    dump_json,
    fixtures,
    identities,
    ok_json,
)

Answers = fixtures.Answers


def _stored_company_types(conn, me) -> list[str] | None:
    row = identities.user_row(conn, me.ident)
    assert row is not None, "the account should exist"
    sf = identities.saved_filters_row(conn, row["id"])
    return None if sf is None else sf["company_category"]


def test_ob10_finish_on_question_4_saves_the_company_types(identity, conn, case_dir):
    me = identity("OB-10")
    body = ok_json(
        me.post(ONBOARDING, fixtures.HEADLINE_UI.body(skipped=False, step=4)),
        "POST /api/users/onboarding (finish on question 4)",
    )
    dump_json(case_dir / "onboarding.json", body)
    assert body["savedFilters"]["companyCategory"] == [fixtures.BIG_TECH], (
        f"the answer's savedFilters.companyCategory is {body['savedFilters'].get('companyCategory')!r}, "
        f"not the company type sent {[fixtures.BIG_TECH]}"
    )
    assert _stored_company_types(conn, me) == [fixtures.BIG_TECH]
    read_back = ok_json(me.get(SAVED_FILTERS), "GET /api/users/saved-filters")
    assert read_back["companyCategory"] == [fixtures.BIG_TECH]
    # The other answers are saved alongside, unchanged.
    assert read_back["category"] == fixtures.HEADLINE_UI.category


def test_ob10_step_5_is_refused_and_stamps_nothing(identity, conn):
    me = identity("OB-10-step5")
    ok_json(me.get(USERS), "GET /api/users (first sign-in)")
    resp = me.post(ONBOARDING, fixtures.HEADLINE_UI.body(skipped=False, step=5))
    assert resp.status_code == 422, (
        f"step 5 answered {resp.status_code}, not 422 — there are only four questions: {resp.text[:300]}"
    )
    row = identities.user_row(conn, me.ident)
    assert row is not None and row["onboarding_completed_at"] is None, (
        "a refused body stamped the account"
    )


def test_ob10_a_skip_on_question_4_keeps_the_company_types(identity, conn):
    me = identity("OB-10-skip")
    body = ok_json(
        me.post(ONBOARDING, Answers(company_category=["fintech", "ai_labs"]).body(skipped=True, step=4)),
        "POST /api/users/onboarding (Skip on question 4)",
    )
    assert body["onboardingCompletedAt"], "a Skip still ends the questions"
    assert _stored_company_types(conn, me) == ["fintech", "ai_labs"]


def test_ob10_a_body_without_the_key_saves_none_on_a_new_row(identity, conn):
    """An older SPA (three questions) on a brand-new account: no company type."""
    me = identity("OB-10-old-spa")
    body = ok_json(
        me.post(ONBOARDING, fixtures.HEADLINE.body(skipped=False, step=3)),
        "POST /api/users/onboarding (no companyCategory key)",
    )
    assert body["savedFilters"]["companyCategory"] == []
    assert _stored_company_types(conn, me) == []


def test_ob10_a_body_without_the_key_keeps_the_stored_company_types(identity, conn):
    """The mirror of OB-07 for the one column with the keep rule: a stored
    company type survives an onboarding call that does not mention it."""
    me = identity("OB-10-keep")
    ok_json(me.get(USERS), "GET /api/users (creates the row the saved-filters API needs)")
    put = ok_json(
        me.put(
            SAVED_FILTERS,
            {
                "recentTimeWindow": "all",
                "trendTimeWindow": "90d",
                "locations": [],
                "category": [],
                "level": [],
                "subcategory": [],
                "companyCategory": ["ai_labs"],
                "recentActiveKeywordListId": None,
                "trendActiveKeywordListId": None,
            },
        ),
        "PUT /api/users/saved-filters (a stored company type)",
    )
    assert put["companyCategory"] == ["ai_labs"]

    body = ok_json(
        me.post(ONBOARDING, fixtures.HEADLINE.body(skipped=False, step=3)),
        "POST /api/users/onboarding without companyCategory",
    )
    assert body["savedFilters"]["companyCategory"] == ["ai_labs"], (
        f"onboarding without the key wiped the stored company type: "
        f"{body['savedFilters']['companyCategory']!r}"
    )
    assert _stored_company_types(conn, me) == ["ai_labs"]
