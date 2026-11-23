"""OB-03 / OB-04 — finishing stamps the account ONCE and saves the answers, in
one transaction; every later call is a no-op that reports what is stored.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

from conftest import (
    BASE_URL,
    ONBOARDING,
    SAVED_FILTERS,
    USERS,
    api_lists,
    db_now,
    dump_json,
    fixtures,
    identities,
    ok_json,
    parse_ts,
    saved_lists,
)


def test_ob03_finish_stamps_once_and_saves_the_answers(identity, conn, case_dir):
    me = identity("OB-03")
    ok_json(me.get(USERS), "GET /api/users (first sign-in)")
    before = db_now(conn)

    body = ok_json(
        me.post(ONBOARDING, fixtures.HEADLINE.body(skipped=False, step=3)),
        "POST /api/users/onboarding (finish)",
    )
    after = db_now(conn)
    dump_json(case_dir / "onboarding.json", body)

    stamp = parse_ts(body["onboardingCompletedAt"])
    assert before <= stamp <= after, (
        f"the stamp {stamp} is not this request's: it should fall between {before} and {after}"
    )
    saved = body["savedFilters"]
    assert api_lists(saved) == fixtures.HEADLINE.as_saved(), (
        f"the response's savedFilters {api_lists(saved)} are not the answers sent "
        f"{fixtures.HEADLINE.as_saved()}"
    )

    # --- The database: stamped AND saved, together ---------------------------
    row = identities.user_row(conn, me.ident)
    assert row is not None and row["onboarding_completed_at"] == stamp, (
        f"users.onboarding_completed_at is {row and row['onboarding_completed_at']!r}, "
        f"the response said {stamp}"
    )
    sf = identities.saved_filters_row(conn, row["id"])
    assert sf is not None, "the account is stamped but has NO user_saved_filters row — the answers were lost"
    assert saved_lists(sf) == fixtures.HEADLINE.as_saved(), (
        f"user_saved_filters holds {saved_lists(sf)}, not the answers {fixtures.HEADLINE.as_saved()}"
    )
    # A NEW row gets the app's defaults for the two windows, not the columns'
    # own stale DB defaults ('3h' / '7d').
    assert (sf["recent_time_window"], sf["trend_time_window"]) == (
        fixtures.NEW_ROW_RECENT_WINDOW,
        fixtures.NEW_ROW_TREND_WINDOW,
    ), (
        f"a new saved-filters row got windows ({sf['recent_time_window']!r}, "
        f"{sf['trend_time_window']!r}); expected ('all', '90d'). '3h'/'7d' are the column "
        "defaults leaking into a row the INSERT should have set explicitly"
    )
    assert sf["recent_active_keyword_list_id"] is None and sf["trend_active_keyword_list_id"] is None

    # --- Every read agrees -----------------------------------------------------
    me_now = ok_json(me.get(USERS), "GET /api/users (after finishing)")
    assert me_now["onboardingCompletedAt"] is not None, (
        "GET /api/users still reports the account as NOT onboarded after it finished — "
        "the next sign-in would ask again"
    )
    assert parse_ts(me_now["onboardingCompletedAt"]) == stamp, (
        f"GET /api/users reports {me_now['onboardingCompletedAt']!r}, the onboarding answer said {stamp}"
    )
    read_back = ok_json(me.get(SAVED_FILTERS), "GET /api/users/saved-filters")
    assert read_back == saved, (
        f"GET /api/users/saved-filters {read_back} disagrees with the onboarding answer {saved}"
    )


def test_ob04_a_second_call_changes_nothing_and_the_first_answers_win(identity, conn):
    me = identity("OB-04")
    first = ok_json(me.post(ONBOARDING, fixtures.HEADLINE.body(skipped=False, step=3)), "first POST")
    row = identities.user_row(conn, me.ident)
    assert row is not None
    sf_first = identities.saved_filters_row(conn, row["id"])
    assert sf_first is not None

    # A different set of answers, and a Skip this time — neither may matter.
    second = ok_json(me.post(ONBOARDING, fixtures.OTHER.body(skipped=True, step=1)), "second POST")

    assert second["onboardingCompletedAt"] == first["onboardingCompletedAt"], (
        f"a second call re-stamped the account: {first['onboardingCompletedAt']} -> "
        f"{second['onboardingCompletedAt']}"
    )
    assert api_lists(second["savedFilters"]) == fixtures.HEADLINE.as_saved(), (
        f"the second call's answers replaced the first: now {api_lists(second['savedFilters'])}, "
        f"should still be {fixtures.HEADLINE.as_saved()}"
    )
    row_after = identities.user_row(conn, me.ident)
    sf_after = identities.saved_filters_row(conn, row["id"])
    assert row_after is not None and row_after["onboarding_completed_at"] == row["onboarding_completed_at"]
    assert sf_after is not None and saved_lists(sf_after) == fixtures.HEADLINE.as_saved()
    # "Writes NOTHING": not even a no-op UPDATE of the saved-filters row.
    assert sf_after["updated_at"] == sf_first["updated_at"], (
        "the second call touched user_saved_filters (updated_at moved) — the IS NULL guard is "
        "supposed to make it write nothing at all"
    )


def test_ob04_two_concurrent_first_calls_stamp_once_with_one_set_of_answers(identity, conn, case_dir):
    """A double tap, or two tabs, on a brand-new account — fired at the same
    instant, with NO prior GET, so the two requests also race to create the
    users row. Three rounds, because one round may not overlap at all."""
    for round_no in range(3):
        me = identity(f"OB-04c{round_no}")
        bodies = [
            fixtures.HEADLINE.body(skipped=False, step=3),
            fixtures.OTHER.body(skipped=True, step=2),
        ]
        barrier = threading.Barrier(len(bodies))

        def fire(body: dict) -> httpx.Response:
            with httpx.Client(
                base_url=BASE_URL, timeout=30.0, headers={"Authorization": f"Bearer {me.token}"}
            ) as c:
                barrier.wait()
                return c.post(ONBOARDING, json=body)

        with ThreadPoolExecutor(max_workers=len(bodies)) as pool:
            responses = list(pool.map(fire, bodies))
        dump_json(
            case_dir / f"round-{round_no}.json",
            [{"status": r.status_code, "body": r.text[:2000]} for r in responses],
        )
        for r in responses:
            assert r.status_code == 200, (
                f"round {round_no}: a concurrent first POST answered {r.status_code}: {r.text[:400]}"
            )
        a, b = (r.json() for r in responses)
        assert a["onboardingCompletedAt"] == b["onboardingCompletedAt"], (
            f"round {round_no}: two concurrent calls reported two stamps "
            f"({a['onboardingCompletedAt']} vs {b['onboardingCompletedAt']}) — it was stamped twice"
        )
        assert api_lists(a["savedFilters"]) == api_lists(b["savedFilters"]), (
            f"round {round_no}: the two calls disagree about what is saved"
        )
        winner = api_lists(a["savedFilters"])
        assert winner in (fixtures.HEADLINE.as_saved(), fixtures.OTHER.as_saved()), (
            f"round {round_no}: the saved answers {winner} are a MIX of the two requests, not one "
            "request's answers — the stamp and the answers were not written together"
        )

        rows = identities.user_rows(conn, me.ident)
        assert len(rows) == 1, f"round {round_no}: {len(rows)} users rows for one identity"
        assert rows[0]["onboarding_completed_at"] == parse_ts(a["onboardingCompletedAt"])
        sf = identities.saved_filters_row(conn, rows[0]["id"])
        assert sf is not None and saved_lists(sf) == winner
