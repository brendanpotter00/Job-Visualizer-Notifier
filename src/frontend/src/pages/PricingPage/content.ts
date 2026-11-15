import { ROUTES } from '../../config/routes';

/**
 * Every word on /pricing. Owner-reviewed in the html plan
 * (docs/implementations/pricingStripe/plan.html), 2026-11-15:
 * - Free is five ruled rows, no bullets.
 * - Pro is "Everything in Free, plus" over ONE line set large (option B) —
 *   no list to pad, no "cancel any time", no "new Pro features" line.
 * - The Free MCP row says "Limited MCP access", no number, until the limiter ships.
 * - No FAQ and no "billed through Stripe" note.
 */

/** Display only. The amount charged is the Stripe Price (`STRIPE_PRICE_ID_PRO`). */
export const PRO_PRICE_USD = 6;

/** How often /pricing re-reads the plan after Checkout, waiting for the webhook. */
export const ACTIVATION_POLL_MS = 2000;
/** Stop polling after this and tell the reader to refresh instead. */
export const ACTIVATION_POLL_LIMIT_MS = 60_000;

/** Where a signed-out "Sign in to upgrade" lands after Auth0, to resume checkout. */
export const PRICING_RESUME_PATH = `${ROUTES.PRICING}?intent=pro`;

export const PRICING_CONTENT = {
  seo: {
    title: 'Pricing · onesecondswe',
    description:
      'onesecondswe is free to browse. Pro is $6 a month for unlimited MCP access to fresh software engineering job postings.',
  },
  eyebrow: 'Pricing',
  headline: 'Free to browse. $6 a month for unlimited MCP.',
  free: {
    name: 'Free',
    price: '$0',
    rows: [
      'Unlimited job access',
      'Curated companies',
      'Saved filters',
      'Hiring trends',
      'Limited MCP access',
    ],
    cta: { label: 'Browse jobs', to: ROUTES.RECENT_JOBS },
  },
  pro: {
    name: 'Pro',
    price: `$${PRO_PRICE_USD}`,
    period: '/ month',
    plus: 'Everything in Free, plus',
    headline: 'Unlimited MCP access',
    cta: {
      signedOut: 'Sign in to upgrade',
      upgrade: 'Upgrade to Pro',
      manage: 'Manage billing',
      included: 'Included with your account',
    },
    unavailable: 'Checkout is not open yet.',
  },
  notices: {
    mcpLimit: 'You reached the free MCP limit. Pro removes it.',
    checkoutCanceled: 'Checkout canceled. You were not charged.',
    activating: 'Payment received. Turning on Pro…',
    activatingSlow: 'Payment received. Pro can take a minute to turn on. Refresh this page.',
    active: 'You’re on Pro.',
    startFailed: 'Couldn’t open checkout. Try again.',
  },
} as const;
