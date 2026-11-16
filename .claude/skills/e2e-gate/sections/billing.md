# Billing — e2e gate runbook

Cases: `e2e/billing/CASES.md`. Design: `e2e/billing/PLAN.md`.

## Run it

```bash
e2e/run.sh billing              # full gate
e2e/run.sh billing --fast       # API tier only
e2e/run.sh billing --case BL-07 # one case
e2e/run.sh billing --keep-up    # leave the stack and stripe listen up for a fix loop
```

**$0.** Stripe sandbox only; a live key is refused by `run.sh`, `stripe_env.py` and
`stack_app.py`. Needs the Stripe CLI logged in (`stripe login`) to the same sandbox as
`STRIPE_SECRET_KEY` (shell or repo-root `.env.local`). Local-only, never CI.

Stack `:8204`/`:3204`, database `jobscraper_e2e_billing`, its own lock — runs alongside the
other sections.

## When to run it

Before "ready to test" on anything touching:

- `src/backend/api/services/billing_service.py`, `services/entitlements.py`, `routers/billing.py`
- the `user_subscriptions` / `stripe_events` models or migrations
- `src/frontend/src/pages/PricingPage/`, `features/billing/`, `AccountPage/PlanSection.tsx`
- `features/auth/useAuth.ts` (`loginWithReturnTo`), `features/auth/returnTo.ts`, `app/HomeRoute.tsx`

## Reading a red

`e2e/billing/artifacts/<run>/summary.md`, then `cases/<test>/step.txt` (names the step that
timed out or failed), then `stack/backend.log` and `stack/stripe-listen.log` — a webhook that
never arrived shows as a missing line in the listen log; one that arrived and failed shows a
`[500]` there and a traceback in the backend log.

| Symptom | Cause | Fix |
|---|---|---|
| Every case BLOCKED | Sandbox unreachable at preflight | Network; re-run |
| `stripe listen did not become ready` | CLI not logged in, or logged in to another account | `stripe login`, pick the sandbox |
| `Stripe rejected the key` | Key revoked or from another account | `docs/implementations/pricingStripe/set_stripe_key.sh` |
| UI cases fail on the Checkout form | Stripe changed the hosted page | Re-probe the selectors in `ui/helpers.ts` (`payOnCheckout`) |

Do not loosen an assertion to match a failure in the billing code — report the bug.
