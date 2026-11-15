# Stripe billing — setup and test runbook

The plan this implements (owner-reviewed, with UI mockups): [`plan.html`](./plan.html)
(open `plan.packed.html` in a browser).

## One-time Stripe setup (test mode)

1. Create a Stripe account and stay in **Test mode** (Sandbox).
2. Product catalog → add product **"onesecondswe Pro"**, recurring price **$6.00 USD / month**. Copy the `price_…` id.
3. Settings → Billing → **Customer portal** → allow *cancel subscriptions (at end of billing period)* and *update payment methods* → Save. (The Portal is what "Manage billing" opens.)
4. Developers → API keys → copy the **secret** key `sk_test_…`.

## Local

Backend `.env.local` (repo root):

```
STRIPE_SECRET_KEY=sk_test_…
STRIPE_PRICE_ID_PRO=price_…
PUBLIC_APP_URL=http://localhost:3000
STRIPE_WEBHOOK_SECRET=whsec_…   # printed by `stripe listen` below
```

```bash
brew install stripe/stripe-cli/stripe
stripe login
stripe listen --forward-to localhost:8000/api/billing/webhook   # leave running; copy its whsec_…
```

Run the backend + `npm run dev:vercel -w src/frontend`, sign in, open `/pricing`.

## Test matrix

| # | Do | Expect |
|---|----|--------|
| 1 | Upgrade, card `4242 4242 4242 4242`, any future date / CVC | Back on `/pricing` → "Turning on Pro…" → "You're on Pro."; button becomes **Manage billing** |
| 2 | Card `4000 0000 0000 0002` | Checkout shows "declined"; still Free |
| 3 | Card `4000 0025 0000 3155` | 3-D Secure challenge → Pro |
| 4 | Manage billing → cancel | Row `cancel_at_period_end = true`; `stripe trigger customer.subscription.deleted` (or a Test Clock) → Free |
| 5 | Test Clock, card `4000 0000 0000 0341`, advance one month | `past_due`, still Pro; advance 3 more days → Free; update card → Pro |
| 6 | `stripe events resend evt_…` | 200, no second write (`stripe_events`) |
| 7 | `curl -X POST localhost:8000/api/billing/webhook -d '{}'` | 400 |
| 8 | `/pricing?reason=mcp_limit` | One line: "You reached the free MCP limit. Pro removes it." |

Check the row: `SELECT plan, status, past_due_since FROM user_subscriptions;`

Query plans (POSTGRES-PRINCIPLES §5): `EXPLAIN (ANALYZE, BUFFERS)` the `is_pro()` read
(`WHERE user_id = …`) and the two webhook lookups (`WHERE stripe_customer_id = …`,
`stripe_subscription_id`) → each an Index Scan on the PK / UNIQUE index, no Seq Scan.

## Production (later — prod stays unconfigured until then)

With the Stripe vars unset in Railway, `/pricing` renders with **Upgrade disabled**
("Checkout is not open yet.") and every billing route except the read is a 503.

1. Railway → backend service → Variables: `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID_PRO`,
   `PUBLIC_APP_URL=https://onesecondswe.dev`.
2. Stripe Dashboard → Developers → Webhooks → **Add endpoint**:
   `https://<railway-backend-host>/api/billing/webhook` (the Railway origin, NOT Vercel),
   events: `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.payment_failed`, `invoice.paid`. Copy its signing secret into Railway as
   `STRIPE_WEBHOOK_SECRET` (it is NOT the `stripe listen` one).
3. Switch to live keys + a live price only at launch.

`/account`'s Plan card stays hidden until `VITE_ACCOUNT_PLAN_CARD_ENABLED=true` is set in
Vercel (build-time).
