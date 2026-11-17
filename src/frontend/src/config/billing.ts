/**
 * Billing visibility. `/pricing` itself stays reachable by URL either way.
 */
export interface BillingConfig {
  /** True only when `VITE_ACCOUNT_PLAN_CARD_ENABLED` is exactly the string `'true'`. */
  showAccountPlanCard: boolean;
  /** "Pricing" in the landing header. Hard-coded off until there is something to sell. */
  showPricingNav: boolean;
}

export const BILLING_CONFIG: BillingConfig = {
  showAccountPlanCard: import.meta.env.VITE_ACCOUNT_PLAN_CARD_ENABLED === 'true',
  showPricingNav: false,
};
