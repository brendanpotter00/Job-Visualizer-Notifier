import { useCallback, useEffect, useState } from 'react';
import { useAppDispatch } from '../../app/hooks';
import { extractErrorMessage } from '../../lib/errors';
import {
  billingApi,
  goToStripe,
  useCreateCheckoutSessionMutation,
  useCreatePortalSessionMutation,
} from './billingApi';

/** Send the browser to Stripe Checkout (`upgrade`) or the Customer Portal (`manage`). */
export function useStripeRedirect(fallbackError: string) {
  const dispatch = useAppDispatch();
  const [startCheckout, checkoutState] = useCreateCheckoutSessionMutation();
  const [openPortal, portalState] = useCreatePortalSessionMutation();
  const [redirecting, setRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Back from Stripe via the bfcache, the page is restored mid-redirect.
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) setRedirecting(false);
    };
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, []);

  const go = useCallback(
    async (request: () => Promise<{ url: string }>) => {
      setError(null);
      try {
        const { url } = await request();
        setRedirecting(true);
        goToStripe(url);
      } catch (err) {
        setError(extractErrorMessage(err, fallbackError));
        // 409: already subscribed, so the cached plan is stale.
        if ((err as { status?: unknown } | null)?.status === 409) {
          dispatch(billingApi.util.invalidateTags(['Subscription']));
        }
      }
    },
    [dispatch, fallbackError]
  );

  const upgrade = useCallback(() => void go(() => startCheckout().unwrap()), [go, startCheckout]);
  const manage = useCallback(() => void go(() => openPortal().unwrap()), [go, openPortal]);

  return {
    upgrade,
    manage,
    error,
    busy: redirecting || checkoutState.isLoading || portalState.isLoading,
  };
}
