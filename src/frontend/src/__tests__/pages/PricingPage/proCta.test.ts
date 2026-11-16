import { describe, it, expect } from 'vitest';
import { resolveProCta } from '../../../pages/PricingPage/proCta';
import { safeReturnTo } from '../../../features/auth/returnTo';
import { describePlan } from '../../../pages/AccountPage/planView';
import type { SubscriptionStatus } from '../../../features/billing/billingApi';

const FREE: SubscriptionStatus = {
  plan: 'free',
  status: null,
  isPro: false,
  hasSubscription: false,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  pastDueSince: null,
  graceEndsAt: null,
  billingEnabled: true,
};
const base = { isAuthenticated: true, authLoading: false, subscriptionLoading: false };

describe('resolveProCta', () => {
  it('waits for auth', () => {
    expect(resolveProCta({ ...base, authLoading: true, subscription: undefined })).toEqual({
      kind: 'loading',
    });
  });
  it('asks a signed-out visitor to sign in', () => {
    expect(resolveProCta({ ...base, isAuthenticated: false, subscription: undefined })).toEqual({
      kind: 'signin',
    });
  });
  it('waits for the subscription read', () => {
    expect(resolveProCta({ ...base, subscription: undefined, subscriptionLoading: true })).toEqual({
      kind: 'loading',
    });
  });
  it('offers Upgrade to a free user, disabled while billing is unconfigured', () => {
    expect(resolveProCta({ ...base, subscription: FREE })).toEqual({
      kind: 'upgrade',
      disabled: false,
    });
    expect(resolveProCta({ ...base, subscription: { ...FREE, billingEnabled: false } })).toEqual({
      kind: 'upgrade',
      disabled: true,
    });
  });
  it('sends any live subscription to the Portal, even a lapsed one', () => {
    const lapsed = {
      ...FREE,
      plan: 'pro' as const,
      status: 'past_due',
      hasSubscription: true,
      isPro: false,
    };
    expect(resolveProCta({ ...base, subscription: lapsed })).toEqual({ kind: 'manage' });
  });
  it('just back from a paid Checkout: disabled until the webhook lands (no double billing)', () => {
    expect(resolveProCta({ ...base, subscription: FREE, returnedFromCheckout: true })).toEqual({
      kind: 'activating',
    });
    const landed = {
      ...FREE,
      plan: 'pro' as const,
      status: 'active',
      isPro: true,
      hasSubscription: true,
    };
    expect(resolveProCta({ ...base, subscription: landed, returnedFromCheckout: true })).toEqual({
      kind: 'manage',
    });
  });
  it('shows Pro without a subscription (admins) as included', () => {
    expect(resolveProCta({ ...base, subscription: { ...FREE, isPro: true } })).toEqual({
      kind: 'included',
    });
  });
});

describe('safeReturnTo', () => {
  it.each([
    ['/pricing?intent=pro', '/pricing?intent=pro'],
    ['/', '/'],
    ['https://evil.example/x', null],
    ['//evil.example/x', null],
    ['/\\evil.example', null],
    ['pricing', null],
    [undefined, null],
    [42, null],
  ])('%s → %s', (input, expected) => {
    expect(safeReturnTo(input)).toBe(expected);
  });
});

describe('describePlan (the /account card)', () => {
  it('free', () => {
    expect(describePlan(FREE)).toMatchObject({ plan: 'Free', action: 'upgrade' });
  });
  it('active', () => {
    const v = describePlan({
      ...FREE,
      plan: 'pro',
      status: 'active',
      isPro: true,
      hasSubscription: true,
    });
    expect(v).toMatchObject({
      plan: 'Pro',
      tag: 'Active',
      action: 'portal',
      actionLabel: 'Manage billing',
    });
  });
  it('cancel scheduled', () => {
    const v = describePlan({
      ...FREE,
      plan: 'pro',
      status: 'active',
      isPro: true,
      hasSubscription: true,
      cancelAtPeriodEnd: true,
      currentPeriodEnd: '2026-12-15T12:00:00Z',
    });
    expect(v).toMatchObject({ plan: 'Pro', actionLabel: 'Resume Pro' });
  });
  it('past due inside the grace keeps Pro; after it, Free', () => {
    const pastDue = { ...FREE, plan: 'pro' as const, status: 'past_due', hasSubscription: true };
    expect(describePlan({ ...pastDue, isPro: true })).toMatchObject({
      plan: 'Pro',
      actionLabel: 'Update card',
    });
    expect(describePlan({ ...pastDue, isPro: false })).toMatchObject({
      plan: 'Free',
      tag: 'Payment failed',
      actionLabel: 'Update card',
    });
  });
  it.each(['unpaid', 'incomplete', 'paused'])(
    'a live but non-entitled %s subscription is never "Active"',
    (status) => {
      const v = describePlan({ ...FREE, plan: 'pro', status, hasSubscription: true, isPro: false });
      expect(v).toMatchObject({ plan: 'Free', tag: 'Payment needed', actionLabel: 'Update card' });
    }
  );
  it('admin', () => {
    expect(describePlan({ ...FREE, isPro: true })).toMatchObject({ plan: 'Pro', action: null });
  });
});
