"""uvicorn entrypoint for the live-view gate's ``--live`` mode — the ONE stack in this
repo that opens a real Browserbase browser session.

Same single seam as ``e2e/shared/stack/e2e_app.py``: import the REAL ``api.main:app``
and patch ``api.auth.jwt._get_jwks_client`` so a token minted by
``e2e/shared/auth/mint.py`` validates. ``jwt.decode`` still runs for real.

WHY THIS IS NOT ``e2e_app.py``. That module hard-refuses to start when
``CAPTURE_USE_BROWSERBASE`` is true, and it is right to: browser-hours are the
expensive line and the add-companies gate runs constantly. But a hosted live view
*only exists* on a Browserbase capture — our own Chromium has none — so a stack that
cannot open one cannot observe the thing this section is about. Rather than weaken the
guard that protects the frequently-run gate, this module carries its own, inverted
where it has to be and stricter where it can be:

* ``CAPTURE_USE_BROWSERBASE`` must be TRUE. False means no live view, which would make
  every assertion here vacuous — a green run proving nothing is worse than a red one.
* ``BROWSERBASE_API_KEY`` must be present, for the same reason: without it the capture
  falls back and the run reports a configuration mistake as a product result.
* The database must be ``jobscraper_e2e``. A gate that *can* point at the owner's
  database once will point at it at 2am.
* ``CUSTOM_COMPANY_SOURCES_ENABLED`` and ``CUSTOM_COMPANY_DISCOVERY_ENABLED`` must both
  be on, or the add returns 422 and no capture ever starts.

ONE SESSION PER RUN, and the run adds exactly one company. That is ~31s of browser
time, which Browserbase's one-minute minimum rounds to a single billed minute.

Cannot leak into production: this file lives under ``e2e/``, is never imported by
``api.main``, and prod's real ``AUTH0_DOMAIN`` means a token issued by
``e2e.local.test`` fails both signature and issuer there regardless.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

logger = logging.getLogger("e2e.live-view.stack")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "src" / "backend"
for _p in (str(_REPO_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.config import settings  # noqa: E402

_EXPECTED_DB = "jobscraper_e2e"


def _refuse(why: str) -> None:
    raise RuntimeError(f"live-view --live stack refuses to start: {why}")


def _assert_database() -> None:
    name = settings.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if name != _EXPECTED_DB:
        _refuse(f"DATABASE_URL resolves to {name!r}, not {_EXPECTED_DB!r}")


def _assert_browserbase_on() -> None:
    """The inverted guard, and the only one in the repo that reads this way."""
    if not settings.capture_use_browserbase:
        _refuse(
            "CAPTURE_USE_BROWSERBASE is false. Our own Chromium has no hosted live "
            "view, so every assertion in this mode would pass vacuously. Use the "
            "default (deterministic, $0) mode instead of running this half-configured."
        )
    if not settings.browserbase_api_key:
        _refuse(
            "BROWSERBASE_API_KEY is blank. Put it in the repo-root .env.local; run.sh "
            "reads it and exports it."
        )


def _assert_flags() -> None:
    if not settings.custom_company_sources_enabled:
        _refuse("CUSTOM_COMPANY_SOURCES_ENABLED is false — the add endpoint 503s")
    if not settings.custom_company_discovery_enabled:
        _refuse("CUSTOM_COMPANY_DISCOVERY_ENABLED is false — no capture ever starts")


def _assert_auth_domain() -> None:
    if settings.auth0_domain != "e2e.local.test":
        _refuse(
            f"AUTH0_DOMAIN is {settings.auth0_domain!r}, not 'e2e.local.test' — "
            f"env.live was not exported before this process started"
        )


def _patch_jwks_seam() -> None:
    import api.auth.jwt as jwt_module

    from e2e.shared.auth.keypair import public_key

    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key()
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    jwt_module._get_jwks_client = lambda: mock_client
    logger.info("live-view stack: patched api.auth.jwt._get_jwks_client")


_assert_database()
_assert_browserbase_on()
_assert_flags()
_assert_auth_domain()
_patch_jwks_seam()

from api.main import app  # noqa: E402

__all__ = ["app"]

logger.warning(
    "live-view --live stack: THIS RUN WILL BILL ONE BROWSERBASE SESSION. db=%s "
    "capture_use_browserbase=%s discovery_enabled=%s",
    settings.database_url.rsplit("/", 1)[-1],
    settings.capture_use_browserbase,
    settings.custom_company_discovery_enabled,
)
