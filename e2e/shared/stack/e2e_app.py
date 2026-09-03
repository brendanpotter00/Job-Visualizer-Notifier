"""uvicorn entrypoint for the e2e backend (PLAN.md §4, §12 step 3).

Imports the REAL `api.main:app` — same routers, same lifespan, same worker
lanes, same DB migrations — and patches exactly ONE seam:
`api.auth.jwt._get_jwks_client`, the module-level factory
`_validate_auth0_token` calls to get a `PyJWKClient`. It is a plain function
looked up by name at CALL time (not a client built at import time — verified
by reading `api/auth/jwt.py` before writing this, per PLAN.md §4's named
risk), which is the exact seam `api/tests/test_auth.py` already patches with
`unittest.mock.patch("api.auth.jwt._get_jwks_client", ...)`.

`jwt.decode` still runs for real inside `_validate_auth0_token` — algorithm,
audience, issuer, expiry, and the `email`-claim requirement in
`routers/user_companies.py` are all genuinely enforced. The only faked thing
is where the public key came from: our own cached keypair (`auth/keypair.py`)
instead of a real Auth0 JWKS fetch.

Cannot leak into production: this file lives under `e2e/`, is never imported
by `api.main`, and prod's real `AUTH0_DOMAIN` means a token issued by
`e2e.local.test` fails signature AND issuer there regardless.

Run with `uvicorn e2e.shared.stack.e2e_app:app --host 127.0.0.1 --port 8201`
(NOT --reload — PLAN.md §2) from the repo root, with env.e2e's variables
already exported into the shell so `api.config.Settings()` reads them at
import time (pydantic-settings: env vars beat `.env`/`.env.local` file
values).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

logger = logging.getLogger("e2e.stack")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _REPO_ROOT / "src" / "backend"
for _p in (str(_REPO_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import path used throughout src/backend/api itself ("from ..config import
# settings" etc resolves relative to package `api`), so import it the same way
# api/tests/ does: as top-level `api.*` with src/backend on sys.path.
from api.config import settings  # noqa: E402

_EXPECTED_DB = "jobscraper_e2e"


def _assert_e2e_database() -> None:
    """Hard guard (PLAN.md §2): refuse to start against anything but the
    dedicated e2e database. A gate that *can* point at the owner's database
    once will point at it at 2am."""
    url = settings.database_url
    db_name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if db_name != _EXPECTED_DB:
        raise RuntimeError(
            f"e2e_app refuses to start: DATABASE_URL resolves to database "
            f"{db_name!r}, not {_EXPECTED_DB!r}. Refusing to risk touching "
            f"anything but the dedicated e2e clone. (url={url!r})"
        )


def _assert_browserbase_off() -> None:
    """Non-negotiable (PLAN.md, top-level + §2, §7): local Chromium only."""
    if settings.capture_use_browserbase:
        raise RuntimeError(
            "e2e_app refuses to start: CAPTURE_USE_BROWSERBASE is true. The "
            "suite must never bill Browserbase."
        )
    if settings.browserbase_api_key:
        raise RuntimeError(
            "e2e_app refuses to start: BROWSERBASE_API_KEY is set (should be "
            "blank in env.e2e) — the second lock against an accidental "
            "Browserbase run."
        )


def _assert_auth_domain() -> None:
    if settings.auth0_domain != "e2e.local.test":
        raise RuntimeError(
            "e2e_app refuses to start: AUTH0_DOMAIN is "
            f"{settings.auth0_domain!r}, not 'e2e.local.test'. env.e2e was "
            "not exported before this process started."
        )


def _patch_jwks_seam() -> None:
    """Patch api.auth.jwt._get_jwks_client to serve our own keypair's public
    key for ANY token, regardless of `kid` — PLAN.md §4's primary approach."""
    import api.auth.jwt as jwt_module

    from ..auth.keypair import public_key

    pub = public_key()

    mock_signing_key = MagicMock()
    mock_signing_key.key = pub

    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    def _fake_get_jwks_client():
        return mock_client

    jwt_module._get_jwks_client = _fake_get_jwks_client
    logger.info("e2e_app: patched api.auth.jwt._get_jwks_client with the e2e keypair")


_assert_e2e_database()
_assert_browserbase_off()
_assert_auth_domain()
_patch_jwks_seam()

# Imported AFTER the patch so any module-level code in api.main (there is
# none that touches JWKS) would still see the patched seam either way — the
# patch target is a name in api.auth.jwt's namespace, looked up at CALL time
# by _validate_auth0_token, so import order here doesn't actually matter, but
# patch-then-import is the more defensive order and it costs nothing.
from api.main import app  # noqa: E402

__all__ = ["app"]

logger.info(
    "e2e_app: booting against database=%s auth0_domain=%s "
    "capture_use_browserbase=%s custom_company_sources_enabled=%s "
    "custom_company_discovery_enabled=%s",
    settings.database_url.rsplit("/", 1)[-1],
    settings.auth0_domain,
    settings.capture_use_browserbase,
    settings.custom_company_sources_enabled,
    settings.custom_company_discovery_enabled,
)
