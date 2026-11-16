# Billing — case table

Real Stripe **sandbox**, real signed webhooks (`stripe listen`), test clocks for time.
**$0.** Local-only: needs `stripe login`. Stack `:8204`/`:3204`, database
`jobscraper_e2e_billing`. Every case uses a fresh user; every clock is deleted after.

| ID | Proves | Tier |
|---|---|---|
| **BL-01** | New user: Free, billing open. Admin: Pro without paying. The Pro button matches signed-out / free / admin. | API + UI |
| **BL-02** | Upgrade → hosted Checkout → 4242 card → webhook → "You’re on Pro." | UI |
| **BL-03** | `/pricing?intent=pro` (the post-sign-in landing) opens Checkout without a click. | UI |
| **BL-04** | Opening Checkout does not grant Pro. The session sells the Pro price, links the user, returns to this app. | API |
| **BL-05** | A second Checkout expires the first. A live subscriber gets 409. | API |
| **BL-06** | Renewal: charged again, period +1 month, still Pro. | API |
| **BL-07** | Declined renewal: `past_due`, still Pro, `graceEndsAt = pastDueSince + 3 days`. | API |
| **BL-08** | Past the 3-day grace: Free while still `past_due`. | API |
| **BL-09** | Card fixed and invoice paid: `active`, Pro again, grace cleared. | API |
| **BL-10** | Portal: a customer gets a `billing.stripe.com` URL; a user who never checked out gets 404. | API |
| **BL-11** | "Manage billing" opens the portal. | UI |
| **BL-12** | Cancel at period end (flag or `cancel_at`): Pro until the end, then Free; the row is kept. | API |
| **BL-13** | Forged, missing or expired signature: 400, nothing written. Unhandled event type: 200, ignored. | API |
| **BL-14** | Replaying a real delivered event changes nothing. | API |
| **BL-15** | A stale event cannot undo newer state: the handler re-reads Stripe. | API |

## Not covered

- The Auth0 redirect back to `/pricing?intent=pro`: the e2e stack signs in with a minted token. Covered by `src/frontend/src/__tests__/app/HomeRouteReturnTo.test.tsx`.
- The Vercel proxy `api/billing.ts`: the frontend runs under plain `vite dev`, as in every section. Covered by `billing.serverless.test.ts`.
- Screens inside Stripe's portal. BL-12 calls the same API the portal calls.
- The grace clock is wall-clock time in the backend; test clocks cannot move it, so BL-08 moves `past_due_since`.
- The production webhook endpoint (Stripe Dashboard → Railway). See `docs/implementations/pricingStripe/SETUP.md`.
