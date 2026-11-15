/**
 * Feature-flag config for billing UI outside /pricing.
 *
 * CLIENT-side only. Default OFF: there is nothing to charge for yet, so the
 * /account Plan card (Upgrade / Manage billing) ships dark. With the flag off,
 * /account is byte-for-byte what shipped before billing existed — no Plan card
 * and no GET /api/billing/subscription request.
 *
 * /pricing, Stripe Checkout, the webhook and the Customer Portal do NOT read
 * this flag: they stay live so Stripe can be tested end to end.
 */
export interface BillingConfig {
  /** True only when `VITE_ACCOUNT_PLAN_CARD_ENABLED` is exactly the string `'true'`. */
  showAccountPlanCard: boolean;
}

export const BILLING_CONFIG: BillingConfig = {
  showAccountPlanCard: import.meta.env.VITE_ACCOUNT_PLAN_CARD_ENABLED === 'true',
};
