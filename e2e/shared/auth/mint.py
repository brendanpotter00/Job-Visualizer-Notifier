"""Mint an RS256 access token for a named e2e test user (PLAN.md §4).

The backend's `get_current_user` dependency validates RS256 against a remote
JWKS derived from `AUTH0_DOMAIN` (`api/auth/jwt.py`), checks `aud`/`iss`, and
hard-requires an `email` claim. There is no dev/test bypass. So this mints a
REAL token — `jwt.decode` still enforces algorithm, audience, issuer, expiry
and the email claim for real — and `e2e_app.py` is the only thing that is
faked: where the public key that validates it came from.

Two identities exist for exactly one reason: AC-10 (ownership isolation) needs
two distinct users who cannot see each other's companies.
"""

from __future__ import annotations

import time

import jwt as pyjwt

from .keypair import KID, load_or_create_private_key

ISSUER = "https://e2e.local.test/"
AUDIENCE = "https://job-visualizer-notifier.vercel.app/api"

#: The primary test identity — everything except AC-10's isolation check runs
#: as this user.
PRIMARY_USER = {
    "sub": "auth0|e2e-add-companies",
    "email": "e2e+add-companies@jvn.test",
    "given_name": "E2E",
    "family_name": "AddCompanies",
}

#: AC-10's second identity, for the ownership-isolation case only.
OTHER_USER = {
    "sub": "auth0|e2e-other",
    "email": "e2e+other@jvn.test",
    "given_name": "E2E",
    "family_name": "Other",
}


def mint_token(user: dict[str, str] | None = None, *, ttl_seconds: int = 8 * 3600) -> str:
    """A signed RS256 token for `user` (default: the primary test identity).

    `iss`/`aud` match `AUTH0_DOMAIN`/`AUTH0_AUDIENCE` in env.e2e exactly, so
    `validate_token` routes it through the Auth0 branch (never the Google one
    — PLAN.md §4, "Do not use the Google issuer") and `_validate_auth0_token`
    accepts it once `_get_jwks_client` is patched to serve our public key.
    """
    user = user or PRIMARY_USER
    now = int(time.time())
    payload = {
        "sub": user["sub"],
        "email": user["email"],
        "given_name": user.get("given_name"),
        "family_name": user.get("family_name"),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    private_key = load_or_create_private_key()
    return pyjwt.encode(payload, private_key, algorithm="RS256", headers={"kid": KID})


if __name__ == "__main__":
    import sys

    who = OTHER_USER if len(sys.argv) > 1 and sys.argv[1] == "other" else PRIMARY_USER
    print(mint_token(who))
