# Stripe billing — setup

The plan this implements (owner-reviewed, with UI mockups): [`plan.html`](./plan.html)
(open `plan.packed.html` in a browser).

Two Stripe accounts are involved:

| | Account | Used by |
|---|---|---|
| Sandbox | `onesecondswe sandbox` (`acct_1UcD1kEKunIiqlCa`) | local dev, `stripe listen`, the e2e gate |
| Live | `onesecondswe` (`acct_1UcE1FEQ5Mlt8bkS`) | production (Railway) |

## Check where production stands

```bash
bash docs/implementations/pricingStripe/check_prod.sh
```

Read-only. It prints `done` / `TODO` for each step below (step 4 has no API, so check it in
the Dashboard). The Stripe checks need the CLI profile from step 1. The last check sends an
unsigned POST to the production webhook: **401** = billing code not deployed, **503** =
deployed but a Railway variable is missing, **400** = live.

## Production go-live

Do steps 1–7 in any order before or after step 8. Until all four Railway variables are set,
production shows `/pricing` with **Upgrade** disabled ("Checkout is not open yet.") and nobody
can be charged. Stripe pages below are in **live mode**: the Dashboard top bar must not say
"Sandbox" or "Test mode".

1. **Activate the live account.** Open <https://dashboard.stripe.com/account/onboarding> and finish
   every section: business type, business details, account representative, products or services,
   public details (website `https://onesecondswe.dev`), statement descriptor, secure your account,
   review and submit (this accepts Stripe's terms). Then connect the CLI to live mode under its own
   profile, so the default profile stays on the sandbox:

   ```bash
   stripe -p live login            # in the browser, approve the "onesecondswe" account
   ```

   ```bash
   stripe -p live switch acct_1UcE1FEQ5Mlt8bkS --live
   ```

2. **Create the Pro price.** Product catalog → **Create product**: name `Pro`, **Recurring**,
   `$6.00` USD, billing period **Monthly** → Save. Copy the price id (`price_…`) for step 7.

3. **Save the Customer portal.** <https://dashboard.stripe.com/settings/billing/portal>:
   - **Payment methods** on
   - **Cancellations** on, **When cancellations take effect** = *At the end of the billing period*
   - **Upgrades and downgrades** off
   - **Save changes**. Live mode has its own portal settings; "Manage billing" fails until they are saved.

4. **Limit one subscription per customer.** <https://dashboard.stripe.com/settings/checkout> →
   **Subscriptions** → **Limit customers to 1 subscription** on → **Save**. The app already refuses
   a second Checkout; this is Stripe's backstop.

5. **Create the secret key.** <https://dashboard.stripe.com/apikeys> → **Create secret key**, name
   `railway-backend`. Stripe shows it once: paste it straight into Railway in step 7.

6. **Add the webhook.** <https://dashboard.stripe.com/workbench/webhooks> → **+ Add destination**:
   - Events from **Your account**, payload style **Snapshot**, API version `2026-10-28.endive`
     (the version `stripe` 17 pins; thin events carry no object and will not work)
   - Events: `checkout.session.completed`, `customer.subscription.created`,
     `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`,
     `invoice.payment_failed` → **Continue**
   - Destination type **Webhook endpoint** → **Continue**
   - Endpoint URL `https://job-visualizer-notifier-production.up.railway.app/api/billing/webhook`
     (Railway, not Vercel: the signature covers the raw body) → **Create destination**
   - On the destination page, reveal the **Signing secret** (`whsec_…`) for step 7. It is not
     the `stripe listen` secret.

7. **Set the Railway variables.** Railway → project `onesecondswe` → service
   `Job-Visualizer-Notifier` → **Variables**, add:

   ```
   STRIPE_SECRET_KEY=<step 5>
   STRIPE_PRICE_ID_PRO=<step 2>
   STRIPE_WEBHOOK_SECRET=<step 6>
   PUBLIC_APP_URL=https://onesecondswe.dev
   ```

   Then click **Deploy** to apply the staged changes.

8. **Merge PR #364.** Vercel and Railway deploy `main`. The Alembic migration creates
   `user_subscriptions` and `stripe_events` on boot.

9. **Pay once for real.** Run `check_prod.sh` until every line says `done`. Then, signed in with a
   **non-admin** account (admins get Pro free), open <https://onesecondswe.dev/pricing> → **Upgrade
   to Pro** → pay with a real card → expect "You're on Pro." → **Manage billing** → cancel. Refund
   the $6 in Dashboard → **Transactions**.

10. **Optional: show the Plan card on `/account`.** Vercel → Environment Variables →
    `VITE_ACCOUNT_PLAN_CARD_ENABLED=true` (Production), then redeploy. It is read at build time.

## Local (sandbox)

Repo-root `.env.local`:

```
STRIPE_SECRET_KEY=sk_test_…     # bash docs/implementations/pricingStripe/set_stripe_key.sh
STRIPE_PRICE_ID_PRO=price_…     # the sandbox's $6/month Pro price
PUBLIC_APP_URL=http://localhost:3000
STRIPE_WEBHOOK_SECRET=whsec_…   # stripe listen --print-secret
```

`set_stripe_key.sh` reads the key silently and refuses a live key, or one that cannot see
`STRIPE_PRICE_ID_PRO` (a key from a different sandbox).

```bash
npm install -g @stripe/cli
```

```bash
stripe login                    # approve the "onesecondswe sandbox" account
```

```bash
stripe listen --forward-to localhost:8000/api/billing/webhook \
  --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.paid,invoice.payment_failed
```

Run the backend and `npm run dev:vercel -w src/frontend`, sign in with a non-admin account, open
`/pricing`, pay with `4242 4242 4242 4242`.

## Tests

```bash
e2e/run.sh billing
```

Runs BL-01..BL-15 against the sandbox (checkout, renewal, declined card and grace, recovery,
cancel, portal, webhook signature / replay / ordering). Cases: [`e2e/billing/CASES.md`](../../../e2e/billing/CASES.md).
