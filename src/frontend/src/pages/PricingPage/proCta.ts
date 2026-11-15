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
 */
export type ProCta =
  | { kind: 'signin' }
  | { kind: 'loading' }
  | { kind: 'upgrade'; disabled: boolean }
  | { kind: 'manage' }
  | { kind: 'included' };

export interface ProCtaInput {
  isAuthenticated: boolean;
  authLoading: boolean;
  subscription: SubscriptionStatus | undefined;
  subscriptionLoading: boolean;
}

export function resolveProCta({
  isAuthenticated,
  authLoading,
  subscription,
  subscriptionLoading,
}: ProCtaInput): ProCta {
  if (authLoading) return { kind: 'loading' };
  if (!isAuthenticated) return { kind: 'signin' };
  if (!subscription)
    return subscriptionLoading ? { kind: 'loading' } : { kind: 'upgrade', disabled: true };
  if (subscription.hasSubscription) return { kind: 'manage' };
  if (subscription.isPro) return { kind: 'included' };
  return { kind: 'upgrade', disabled: !subscription.billingEnabled };
}
