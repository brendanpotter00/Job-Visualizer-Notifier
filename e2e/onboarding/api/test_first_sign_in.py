"""OB-01 / OB-02 — a brand-new account starts UNSTAMPED, and stays unstamped
until it answers.

The SPA opens the questions for `onboardingCompletedAt === null` and for
nothing else, so these two cases pin the only value that lets the feature
happen at all. The two ways it can silently never happen:

* the column gets a server default (or the INSERT sets it) — every new account
  is born stamped and nobody ever sees the questions;
* something on the sign-in path stamps it (a read, a visit) — the questions
  show once, the user closes the tab half-way, and they never come back.
"""

from __future__ import annotations

from conftest import USERS, VISIT, dump_json, identities, ok_json


def test_ob01_first_sign_in_creates_the_account_unstamped(identity, conn, case_dir):
    me = identity("OB-01")
    # Precondition (the identity factory asserted it; restated because it is
    # the whole meaning of "first"): no row before the first call.
    assert identities.user_rows(conn, me.ident) == []

    body = ok_json(me.get(USERS), "GET /api/users (first sign-in)")
    dump_json(case_dir / "users.json", body)

    # PRESENT and null — not absent. The SPA reads an ABSENT key as "an older
    # backend, never ask", so a serializer that dropped None fields would turn
    # the feature off while this assertion's weaker cousin (`.get(...) is None`)
    # stayed green.
    assert "onboardingCompletedAt" in body, (
        f"GET /api/users has no onboardingCompletedAt key at all: {sorted(body)} — the SPA "
        "treats a missing key as an older backend and never asks"
    )
    assert body["onboardingCompletedAt"] is None, (
        f"a brand-new account came back already stamped ({body['onboardingCompletedAt']!r}) — "
        "a server default or the INSERT is stamping new rows, so nobody will ever see the questions"
    )

    rows = identities.user_rows(conn, me.ident)
    assert len(rows) == 1, f"first sign-in should create exactly one users row, found {len(rows)}"
    assert rows[0]["onboarding_completed_at"] is None, (
        f"users.onboarding_completed_at is {rows[0]['onboarding_completed_at']!r} for a brand-new row"
    )


def test_ob02_signing_in_again_before_answering_still_asks(identity, conn):
    me = identity("OB-02")
    first = ok_json(me.get(USERS), "GET /api/users (first)")
    assert first["onboardingCompletedAt"] is None

    # Every full page load records a visit. It must not count as an answer.
    resp = me.post(VISIT, {})
    assert resp.status_code == 204, f"POST /api/users/visit answered {resp.status_code}: {resp.text[:300]}"

    second = ok_json(me.get(USERS), "GET /api/users (second sign-in)")
    assert second["onboardingCompletedAt"] is None, (
        f"after a GET and a visit the account reads as stamped ({second['onboardingCompletedAt']!r}) — "
        "something on the sign-in path stamps it, so an account that closed the tab half-way "
        "will never be asked again"
    )
    assert second["id"] == first["id"], "signing in again returned a different account id"

    rows = identities.user_rows(conn, me.ident)
    assert len(rows) == 1, f"signing in again created a second users row ({len(rows)} rows)"
    row = rows[0]
    assert row["onboarding_completed_at"] is None
    # The mirror that makes the NULL meaningful: the visit DID write to this
    # row, so "still NULL" is the stamp being left alone, not the call missing.
    assert row["visit_count"] >= 1, (
        f"visit_count is {row['visit_count']} — POST /api/users/visit never reached this row, so "
        "'the visit did not stamp it' proves nothing"
    )
