"""uvicorn entrypoint for the company-name-search intent test's backend.

Same one seam as ``e2e/shared/stack/e2e_app.py``: import the REAL ``api.main:app``
and patch ``api.auth.jwt._get_jwks_client`` so a token minted by
``e2e/shared/auth/mint.py`` validates. ``jwt.decode`` still runs for real —
algorithm, audience, issuer, expiry and the ``email`` claim are all genuinely
enforced. The only faked thing is where the public key came from.

WHY THIS IS NOT ``e2e_app.py``. That module hard-refuses to start if
``BROWSERBASE_API_KEY`` is set, because the add-companies gate must never bill.
This suite tests the one feature whose whole first step IS a paid Browserbase
Search call, so it needs the key. Rather than weaken the add-companies guard —
which exists for a good reason and protects a suite that runs far more often —
this module carries its OWN guards, inverted where they have to be and STRICTER
where they can be:

* ``BROWSERBASE_API_KEY`` must be present. Without it every case would 503 and the
  run would report an outage as a result.
* ``CAPTURE_USE_BROWSERBASE`` must still be FALSE. Search is $0.007 per call;
  Browserbase BROWSER HOURS are the expensive thing, and ``search-by-name`` never
  needs one. So this suite bills searches and can never bill a browser-hour — the
  original non-negotiable's actual intent, kept.
* The database must be ``jobscraper_e2e``. This endpoint writes nothing, but a gate
  that *can* point at the owner's database once will point at it at 2am.
* ``COMPANY_NAME_SEARCH_ENABLED`` and ``CUSTOM_COMPANY_SOURCES_ENABLED`` must both
  be on, or the route 503s and every case reads as an outage instead of a result.

Cannot leak into production: this file lives under ``e2e/``, is never imported by
``api.main``, and prod's real ``AUTH0_DOMAIN`` means a token issued by
``e2e.local.test`` fails both signature and issuer there regardless.

Launched by ``run.sh`` as::

    PYTHONPATH=<section-dir>:<repo-root> python -m uvicorn stack_app:app \
        --host 127.0.0.1 --port 8202

(module name ``stack_app``, not a dotted path, because ``company-name-search`` has a
hyphen in it and is not an importable package name.)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

logger = logging.getLogger("e2e.name-search.stack")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "src" / "backend"
for _p in (str(_REPO_ROOT), str(_BACKEND_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.config import settings  # noqa: E402

_EXPECTED_DB = "jobscraper_e2e"


def _refuse(why: str) -> None:
    raise RuntimeError(f"name-search stack refuses to start: {why}")


def _assert_database() -> None:
    url = settings.database_url
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if name != _EXPECTED_DB:
        _refuse(
            f"DATABASE_URL resolves to {name!r}, not {_EXPECTED_DB!r}. The published-"
            f"company cases (Databricks, Meta vs Anthropic/Cohere, IBM vs Harvey) are "
            f"only meaningful against the seeded clone."
        )


def _assert_billing_shape() -> None:
    """Search: yes, deliberately, that is the feature. Browser hours: never."""
    if not settings.browserbase_api_key:
        _refuse(
            "BROWSERBASE_API_KEY is blank. This suite MUST spend real searches — "
            "without the key every case 503s and the run would report an outage as "
            "a result. Put the key in the repo-root .env.local; run.sh reads it."
        )
    if settings.capture_use_browserbase:
        _refuse(
            "CAPTURE_USE_BROWSERBASE is true. search-by-name never needs a remote "
            "browser, and browser-hours are the expensive line. Searches yes, "
            "browser hours no."
        )


def _assert_flags() -> None:
    if not settings.custom_company_sources_enabled:
        _refuse("CUSTOM_COMPANY_SOURCES_ENABLED is false — the route 503s")
    if not settings.company_name_search_enabled:
        _refuse("COMPANY_NAME_SEARCH_ENABLED is false — the route 503s")


def _assert_auth_domain() -> None:
    if settings.auth0_domain != "e2e.local.test":
        _refuse(
            f"AUTH0_DOMAIN is {settings.auth0_domain!r}, not 'e2e.local.test' — "
            f"env.name-search was not exported before this process started"
        )


def _patch_jwks_seam() -> None:
    import api.auth.jwt as jwt_module

    from e2e.shared.auth.keypair import public_key

    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key()
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    jwt_module._get_jwks_client = lambda: mock_client
    logger.info("name-search stack: patched api.auth.jwt._get_jwks_client")


_assert_database()
_assert_billing_shape()
_assert_flags()
_assert_auth_domain()
_patch_jwks_seam()

from api.main import app  # noqa: E402

__all__ = ["app"]

logger.info(
    "name-search stack: db=%s search_enabled=%s browserbase_search_key=%s "
    "capture_use_browserbase=%s",
    settings.database_url.rsplit("/", 1)[-1],
    settings.company_name_search_enabled,
    "present" if settings.browserbase_api_key else "MISSING",
    settings.capture_use_browserbase,
)
