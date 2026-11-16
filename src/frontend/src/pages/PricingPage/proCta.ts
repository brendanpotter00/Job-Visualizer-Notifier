import type { SubscriptionStatus } from '../../features/billing/billingApi';

/**
 * The Pro card's button, from auth + billing state.
 *
 * - `signin`     signed out
 * - `loading`    auth or the subscription read in flight
 * - `upgrade`    free; `disabled` while the backend has no Stripe keys
 * - `manage`     any live subscription, checked before entitlement: a lapsed
 *                user still has a card to fix, and Checkout would bill twice
 * - `included`   Pro without a subscription (admins)
 * - `activating` back from a paid Checkout before the webhook lands; disabled
 *                so it cannot open a second Checkout
 */
export type ProCta =
  | { kind: 'signin' }
  | { kind: 'loading' }
  | { kind: 'upgrade'; disabled: boolean }
  | { kind: 'manage' }
  | { kind: 'included' }
  | { kind: 'activating' };

interface ProCtaInput {
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
