import type { SubscriptionStatus } from '../../features/billing/billingApi';

/**
 * What the Pro card's button is, as a pure function of auth + billing state.
 * Kept out of the component so every branch is unit-testable without Stripe.
 *
 * - `signin`   signed out → "Sign in to upgrade" (Auth0, then back to /pricing)
 * - `loading`  auth or the subscription read is still in flight
 * - `upgrade`  free → "Upgrade to Pro" (Checkout); `disabled` while the backend
 *              has no Stripe keys, so the button never leads to a 503
 * - `manage`   a live subscription (active, past due, cancel scheduled) →
 *              "Manage billing" (Customer Portal). This is checked BEFORE
 *              entitlement on purpose: a lapsed user is not Pro but still has a
 *              card to fix, and Checkout would bill them twice.
 * - `included` Pro without a subscription (admins) → nothing to buy or manage
 * - `activating` back from a paid Checkout, webhook not landed yet → disabled.
 *              The row says "free" until the webhook writes it, so an enabled
 *              Upgrade here would open a SECOND Checkout and bill twice (the
 *              backend also refuses it by asking Stripe; this is the UI half).
 */
export type ProCta =
  | { kind: 'signin' }
  | { kind: 'loading' }
  | { kind: 'upgrade'; disabled: boolean }
  | { kind: 'manage' }
  | { kind: 'included' }
  | { kind: 'activating' };

export interface ProCtaInput {
  isAuthenticated: boolean;
  authLoading: boolean;
  subscription: SubscriptionStatus | undefined;
  subscriptionLoading: boolean;
  /** `?checkout=success` is on the URL: the user just paid. */
  returnedFromCheckout?: boolean;
}

export function resolveProCta({
  isAuthenticated,
  authLoading,
  subscription,
  subscriptionLoading,
  returnedFromCheckout = false,
}: ProCtaInput): ProCta {
  if (authLoading) return { kind: 'loading' };
  if (!isAuthenticated) return { kind: 'signin' };
  if (!subscription)
    return subscriptionLoading ? { kind: 'loading' } : { kind: 'upgrade', disabled: true };
  if (subscription.hasSubscription) return { kind: 'manage' };
  if (subscription.isPro) return { kind: 'included' };
  if (returnedFromCheckout) return { kind: 'activating' };
  return { kind: 'upgrade', disabled: !subscription.billingEnabled };
}
