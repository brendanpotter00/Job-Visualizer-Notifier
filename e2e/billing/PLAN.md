# Billing e2e gate — design

## What it proves

The Pro plan works against Stripe itself: real Checkout, real signed webhooks, real event
shapes for the pinned API version, real renewals and declines. The backend unit tests
(`src/backend/api/tests/test_billing.py`) prove the logic against a fake client; this gate
proves the wiring. Cases: `CASES.md`.

## Shape

| Piece | Choice |
|---|---|
| Stack | `:8204` backend, `:3204` frontend, database `jobscraper_e2e_billing` (schema-only clone), own lock and pidfiles. |
| Entrypoint | `stack_app.py`: the shared `e2e_app` plus three boot guards — sandbox key only, billing fully configured, `PUBLIC_APP_URL` is `:3204`. |
| Webhooks | `run.sh` starts `stripe listen --forward-to :8204/api/billing/webhook` for the six handled events; its secret comes from `stripe listen --print-secret`. |
| Secrets | None under `e2e/`. `STRIPE_SECRET_KEY` from the shell or repo-root `.env.local`; the price is found (or created) by lookup key `pro_monthly`. |
| Users | A fresh identity per case (`e2e+billing-<id>@jvn.test`, minted by `shared/auth/mint.py custom`). A user owns one customer and one subscription row, so sharing one would leak state between cases. |
| Time | One Stripe test clock per case that needs it, deleted at the end of the case. |
| Cleanup | `stripe_env.py cleanup` before and after every run: clocks named `e2e-billing-*`, customers the database links to, and the section's rows. |
| Outage | Sandbox unreachable at preflight → every case BLOCKED, not FAIL. |

## Shared changes (defaults unchanged)

- `stack_up.sh`: `E2E_APP_MODULE` names the uvicorn app.
- `ensure_db.sh`: `E2E_SOURCE_DB` names the clone source.
- `shared/auth`: `mint.py custom <sub> <email>`; `signInContext` also takes a one-off `{ sub, email }`.

## Limits

See `CASES.md` → "Not covered". The UI tier pays through Stripe's hosted page; if Stripe
changes that page, `ui/helpers.ts` `payOnCheckout` is the one place to update.
