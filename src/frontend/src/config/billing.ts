/** The /account Plan card ships off by default. /pricing does not read this flag. */
export interface BillingConfig {
  /** True only when `VITE_ACCOUNT_PLAN_CARD_ENABLED` is exactly the string `'true'`. */
  showAccountPlanCard: boolean;
}

export const BILLING_CONFIG: BillingConfig = {
  showAccountPlanCard: import.meta.env.VITE_ACCOUNT_PLAN_CARD_ENABLED === 'true',
};
