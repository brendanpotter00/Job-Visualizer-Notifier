import type { SubscriptionStatus } from '../../features/billing/billingApi';
import { PRO_PRICE_USD } from '../PricingPage/content';

function formatDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

interface PlanView {
  plan: string;
  tag?: string;
  line: string;
  danger?: boolean;
  action: 'upgrade' | 'portal' | null;
  actionLabel?: string;
}

/** Each subscription state → what the card says. Mirrors the plan's state machine. */
export function describePlan(sub: SubscriptionStatus): PlanView {
  if (sub.hasSubscription && sub.status === 'past_due') {
    return sub.isPro
      ? {
          plan: 'Pro',
          tag: 'Payment failed',
          line: `Your last payment failed. Update your card by ${formatDate(sub.graceEndsAt)} to keep Pro.`,
          danger: true,
          action: 'portal',
          actionLabel: 'Update card',
        }
      : {
          plan: 'Free',
          tag: 'Payment failed',
          line: 'Pro is paused until your payment goes through.',
          danger: true,
          action: 'portal',
          actionLabel: 'Update card',
        };
  }
  if (sub.hasSubscription && !sub.isPro) {
    // A live subscription that does not entitle: unpaid, incomplete, paused.
    // Never "Pro · Active" — the card must agree with what is enforced.
    return {
      plan: 'Free',
      tag: 'Payment needed',
      line: 'Pro is paused until your payment goes through.',
      danger: true,
      action: 'portal',
      actionLabel: 'Update card',
    };
  }
  if (sub.hasSubscription && sub.cancelAtPeriodEnd) {
    const end = formatDate(sub.currentPeriodEnd);
    return {
      plan: 'Pro',
      tag: `Ends ${end}`,
      line: `You keep Pro until ${end}. Then you move to Free.`,
      action: 'portal',
      actionLabel: 'Resume Pro',
    };
  }
  if (sub.hasSubscription) {
    return {
      plan: 'Pro',
      tag: 'Active',
      line: `$${PRO_PRICE_USD} a month. Renews ${formatDate(sub.currentPeriodEnd)}.`,
      action: 'portal',
      actionLabel: 'Manage billing',
    };
  }
  if (sub.isPro) {
    return { plan: 'Pro', line: 'Included with your account.', action: null };
  }
  return {
    plan: 'Free',
    line: 'Get unlimited MCP calls.',
    action: 'upgrade',
    actionLabel: `Upgrade to Pro · $${PRO_PRICE_USD}/mo`,
  };
}
