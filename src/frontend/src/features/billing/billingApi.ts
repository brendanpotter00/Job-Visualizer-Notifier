import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

/**
 * GET /api/billing/subscription. `plan` is BILLING state (what the current
 * subscription is for); `isPro` is ENTITLEMENT (admins, the 3-day past-due
 * grace). `hasSubscription` is the CTA switch: true → "Manage billing"
 * (Customer Portal), false → "Upgrade to Pro" (Checkout).
 */
export interface SubscriptionStatus {
  plan: 'free' | 'pro';
  status: string | null;
  isPro: boolean;
  hasSubscription: boolean;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  pastDueSince: string | null;
  graceEndsAt: string | null;
  /** False while the backend has no Stripe keys: Upgrade is disabled, not a 503. */
  billingEnabled: boolean;
}

export interface BillingRedirect {
  url: string;
}

interface BillingApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}

export const billingApi = createApi({
  reducerPath: 'billingApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/billing',
    prepareHeaders: async (headers, { extra }) => {
      const { getTokenOrNull } = extra as BillingApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  tagTypes: ['Subscription'],
  endpoints: (builder) => ({
    getSubscription: builder.query<SubscriptionStatus, void>({
      query: () => 'subscription',
      providesTags: ['Subscription'],
    }),
    // Both mutations return a Stripe-hosted URL the caller sends the browser to.
    // Neither changes the subscription by itself — only the webhook does — so
    // neither invalidates the Subscription tag.
    createCheckoutSession: builder.mutation<BillingRedirect, void>({
      query: () => ({ url: 'checkout-session', method: 'POST' }),
    }),
    createPortalSession: builder.mutation<BillingRedirect, void>({
      query: () => ({ url: 'portal-session', method: 'POST' }),
    }),
  }),
});

export const {
  useGetSubscriptionQuery,
  useCreateCheckoutSessionMutation,
  useCreatePortalSessionMutation,
} = billingApi;

/** Send the browser to a Stripe-hosted page. A seam so tests can assert the URL. */
export function goToStripe(url: string): void {
  window.location.assign(url);
}
