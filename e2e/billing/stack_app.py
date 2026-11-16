"""uvicorn entrypoint for the billing e2e backend: the shared `e2e_app` plus
boot guards — a sandbox key only, billing fully configured, and PUBLIC_APP_URL
pointing at this section's frontend."""

from __future__ import annotations

from e2e.shared.stack.e2e_app import app  # noqa: F401 — runs the shared guards + patch

from api.config import settings  # noqa: E402
from api.services.billing_service import billing_configured  # noqa: E402

_key = settings.stripe_secret_key or ""
if not _key.startswith(("sk_test_", "rk_test_")):
    raise RuntimeError(
        "billing stack_app refuses to start: STRIPE_SECRET_KEY is not a sandbox/test key "
        "(expected sk_test_… or rk_test_…). The UI tier pays a real Checkout; with a live "
        "key that would be a real charge."
    )
if not billing_configured():
    raise RuntimeError(
        "billing stack_app refuses to start: billing is not fully configured "
        "(STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID_PRO, PUBLIC_APP_URL). "
        "Run it through e2e/billing/run.sh, which exports all four."
    )
if (settings.public_app_url or "").rstrip("/") != "http://127.0.0.1:3204":
    raise RuntimeError(
        f"billing stack_app refuses to start: PUBLIC_APP_URL={settings.public_app_url!r}, "
        "not this section's frontend http://127.0.0.1:3204."
    )

__all__ = ["app"]
