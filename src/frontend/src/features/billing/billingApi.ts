import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

/** GET /api/billing/subscription. `plan` is billing state; `isPro` is entitlement. */
export interface SubscriptionStatus {
  plan: 'free' | 'pro';
  status: string | null;
  isPro: boolean;
  hasSubscription: boolean;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  pastDueSince: string | null;
  graceEndsAt: string | null;
  billingEnabled: boolean;
}

interface BillingRedirect {
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
    // Only the webhook changes the subscription, so neither mutation invalidates it.
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

/** Send the browser to a Stripe-hosted page (a seam for tests). */
export function goToStripe(url: string): void {
  window.location.assign(url);
}
