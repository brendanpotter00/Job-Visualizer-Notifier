"""OB-08 / OB-09 — only a signed-in caller can write, and an account that
existed before the feature is never asked (and never un-stamped).
"""

from __future__ import annotations

import httpx

from conftest import (
    BASE_URL,
    ONBOARDING,
    USERS,
    fixtures,
    identities,
    ok_json,
    parse_ts,
    sign_in,
)
from e2e.onboarding.identities import Identity
from e2e.shared.auth.mint import mint_token


def _prefixed_user_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM users WHERE left(auth0_id, %s) = %s",
            (len(fixtures.IDENTITY_PREFIX), fixtures.IDENTITY_PREFIX),
        )
        return int(cur.fetchone()["n"])


def test_ob08_no_bearer_is_401_and_writes_nothing(conn):
    before = _prefixed_user_count(conn)
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as anon:
        post = anon.post(ONBOARDING, json=fixtures.HEADLINE.body(skipped=False, step=3))
        get = anon.get(USERS)
    assert post.status_code == 401, (
        f"POST /api/users/onboarding with no bearer answered {post.status_code}: {post.text[:300]}"
    )
    assert get.status_code == 401, f"GET /api/users with no bearer answered {get.status_code}"
    assert _prefixed_user_count(conn) == before, "an anonymous call created a users row"


def test_ob08_a_token_without_an_email_claim_is_401_and_creates_no_row(conn):
    """A perfectly signed token for a real-looking sub, minus `email`. The
    account model keys on email, so this must be refused before any write."""
    ident = identities.new_identity("OB-08")
    token = mint_token({"sub": ident.sub, "email": None})
    try:
        with httpx.Client(
            base_url=BASE_URL, timeout=30.0, headers={"Authorization": f"Bearer {token}"}
        ) as c:
            resp = c.post(ONBOARDING, json=fixtures.HEADLINE.body(skipped=False, step=3))
        assert resp.status_code == 401, (
            f"a token with no email claim answered {resp.status_code}, not 401: {resp.text[:300]}"
        )
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM users WHERE auth0_id = %s", (ident.sub,))
            assert int(cur.fetchone()["n"]) == 0, "an email-less token created a users row"

        # The mirror: the SAME sub WITH an email is accepted — so the 401 above
        # is the missing claim, not a token this stack rejects anyway.
        with_email = sign_in(ident)
        ok_json(with_email.post(ONBOARDING, fixtures.HEADLINE.body(skipped=False, step=3)),
                "the same identity WITH an email claim")
    finally:
        identities.purge(conn, [ident.sub])


def test_ob08_a_token_signed_by_another_key_is_401(conn):
    """Signature is really checked: the patched JWKS seam serves ONE key, and a
    token signed by any other is refused before the router runs."""
    import time

    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from e2e.shared.auth.mint import AUDIENCE, ISSUER

    ident = identities.new_identity("OB-08-forged")
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = pyjwt.encode(
        {"sub": ident.sub, "email": ident.email, "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 600},
        stranger,
        algorithm="RS256",
    )
    with httpx.Client(base_url=BASE_URL, timeout=30.0, headers={"Authorization": f"Bearer {forged}"}) as c:
        resp = c.post(ONBOARDING, json=fixtures.HEADLINE.body(skipped=False, step=3))
    assert resp.status_code == 401, f"a forged token answered {resp.status_code}: {resp.text[:300]}"
    assert identities.user_rows(conn, Identity(ident.sub, ident.email)) == []


def test_ob09_a_preexisting_account_is_never_asked_and_never_unstamped(conn):
    acct = fixtures.PREEXISTING
    seeded_stamp = parse_ts(acct.stamped_at)
    me = sign_in(Identity(sub=acct.sub, email=acct.email))

    body = ok_json(me.get(USERS), "GET /api/users (pre-existing account)")
    assert body["onboardingCompletedAt"] is not None, (
        "the pre-existing (backfilled) account reads as NOT onboarded — it would be asked"
    )
    assert parse_ts(body["onboardingCompletedAt"]) == seeded_stamp, (
        f"GET /api/users reports {body['onboardingCompletedAt']}, the seeded stamp is {seeded_stamp}"
    )

    post = ok_json(
        me.post(ONBOARDING, fixtures.HEADLINE.body(skipped=False, step=3)),
        "POST /api/users/onboarding (pre-existing account)",
    )
    assert parse_ts(post["onboardingCompletedAt"]) == seeded_stamp, (
        f"a later call moved the backfilled stamp: {seeded_stamp} -> {post['onboardingCompletedAt']}"
    )
    assert post["savedFilters"]["category"] == [], (
        f"a later call saved answers onto an already-onboarded account: {post['savedFilters']}"
    )

    row = identities.user_row(conn, Identity(acct.sub, acct.email))
    assert row is not None and row["onboarding_completed_at"] == seeded_stamp
    assert identities.saved_filters_row(conn, row["id"]) is None, (
        "the no-op call created a user_saved_filters row for an account that never had one"
    )
