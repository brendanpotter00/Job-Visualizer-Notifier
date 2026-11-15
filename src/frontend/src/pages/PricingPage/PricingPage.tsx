import { useCallback, useEffect, useRef, useState } from 'react';
import { Box, Container, Typography } from '@mui/material';
import { useSearchParams } from 'react-router-dom';
import { RESPONSIVE } from '../../config/responsive';
import { useAuth } from '../../features/auth/useAuth';
import {
  goToStripe,
  useCreateCheckoutSessionMutation,
  useCreatePortalSessionMutation,
  useGetSubscriptionQuery,
} from '../../features/billing/billingApi';
import { extractErrorMessage } from '../../lib/errors';
import { LANDING_CONTENT } from '../LandingPage/content';
import { LandingHeader } from '../LandingPage/sections/LandingHeader';
import {
  ACTIVATION_POLL_LIMIT_MS,
  ACTIVATION_POLL_MS,
  PRICING_CONTENT,
  PRICING_RESUME_PATH,
} from './content';
import { FreePlanCard, ProPlanCard } from './PlanCards';
import { PricingSeo } from './PricingSeo';
import { resolveProCta } from './proCta';

type Notice = { text: string; tone: 'info' | 'error' };

function PricingNotice({ notice }: { notice: Notice }) {
  return (
    <Box
      role={notice.tone === 'error' ? 'alert' : 'status'}
      sx={{
        border: '1px solid',
        borderColor: notice.tone === 'error' ? 'error.main' : 'text.primary',
        color: notice.tone === 'error' ? 'error.main' : 'text.primary',
        borderRadius: 3,
        px: 2,
        py: 1.5,
        mb: 3,
        maxWidth: 880,
      }}
    >
      {notice.text}
    </Box>
  );
}

/**
 * /pricing — Free vs Pro ($6/month, unlimited MCP).
 *
 * Mounted OUTSIDE RootLayout, full-bleed with the landing header, like `/`.
 * Query params it reads:
 * - `?reason=mcp_limit`  the MCP 429's upgradeUrl → one line above the plans
 * - `?intent=pro`        set by "Sign in to upgrade" → resumes Checkout once
 * - `?checkout=success`  Stripe's success_url → poll until the WEBHOOK grants Pro
 *                        (the redirect itself proves nothing)
 * - `?checkout=cancel`   Stripe's cancel_url
 */
export function PricingPage() {
  const {
    isEnabled: authEnabled,
    isAuthenticated,
    isLoading: authLoading,
    loginWithReturnTo,
  } = useAuth();
  const [params, setParams] = useSearchParams();
  const reason = params.get('reason');
  const checkout = params.get('checkout');
  const intent = params.get('intent');

  const subscriptionQuery = useGetSubscriptionQuery(undefined, { skip: !isAuthenticated });
  const subscription = subscriptionQuery.data;
  const { refetch } = subscriptionQuery;

  const [startCheckout, checkoutState] = useCreateCheckoutSessionMutation();
  const [openPortal, portalState] = useCreatePortalSessionMutation();
  const [redirecting, setRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Back-button from Stripe restores this page from the bfcache with the button
  // still "redirecting"; re-enable it.
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) setRedirecting(false);
    };
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, []);

  const cta = resolveProCta({
    isAuthenticated,
    authLoading,
    subscription,
    subscriptionLoading: subscriptionQuery.isLoading,
  });

  // --- after Checkout: poll until the webhook lands (or give up after a minute)
  const awaitingWebhook = checkout === 'success';
  const [pollExpired, setPollExpired] = useState(false);
  useEffect(() => {
    if (!awaitingWebhook) return;
    const timer = setTimeout(() => setPollExpired(true), ACTIVATION_POLL_LIMIT_MS);
    return () => clearTimeout(timer);
  }, [awaitingWebhook]);
  const polling = awaitingWebhook && isAuthenticated && !pollExpired && !subscription?.isPro;
  useEffect(() => {
    if (!polling) return;
    const id = setInterval(() => void refetch(), ACTIVATION_POLL_MS);
    return () => clearInterval(id);
  }, [polling, refetch]);

  const go = useCallback(async (request: () => Promise<{ url: string }>) => {
    setError(null);
    try {
      const { url } = await request();
      setRedirecting(true);
      goToStripe(url);
    } catch (err) {
      setError(extractErrorMessage(err, PRICING_CONTENT.notices.startFailed));
    }
  }, []);
  const onUpgrade = useCallback(() => void go(() => startCheckout().unwrap()), [go, startCheckout]);
  const onManage = useCallback(() => void go(() => openPortal().unwrap()), [go, openPortal]);
  const onSignIn = useCallback(
    () => void loginWithReturnTo(PRICING_RESUME_PATH).catch(() => undefined),
    [loginWithReturnTo]
  );

  // --- back from sign-in with ?intent=pro: resume Checkout exactly once
  const resumed = useRef(false);
  useEffect(() => {
    if (intent !== 'pro' || resumed.current) return;
    if (cta.kind === 'signin' || cta.kind === 'loading') return;
    resumed.current = true;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('intent');
        return next;
      },
      { replace: true }
    );
    // Started from a timer callback, not the effect body (no setState in an
    // effect). Deliberately not cleared on cleanup: removing ?intent re-runs this
    // effect, and the `resumed` ref already makes it fire exactly once.
    if (cta.kind === 'upgrade' && !cta.disabled) window.setTimeout(onUpgrade, 0);
  }, [intent, cta, onUpgrade, setParams]);

  const notice: Notice | null = error
    ? { text: error, tone: 'error' }
    : awaitingWebhook && isAuthenticated
      ? {
          text: subscription?.isPro
            ? PRICING_CONTENT.notices.active
            : pollExpired
              ? PRICING_CONTENT.notices.activatingSlow
              : PRICING_CONTENT.notices.activating,
          tone: 'info',
        }
      : checkout === 'cancel'
        ? { text: PRICING_CONTENT.notices.checkoutCanceled, tone: 'info' }
        : reason === 'mcp_limit'
          ? { text: PRICING_CONTENT.notices.mcpLimit, tone: 'info' }
          : null;

  const busy = redirecting || checkoutState.isLoading || portalState.isLoading;

  return (
    <Box
      sx={{
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        bgcolor: 'background.default',
      }}
    >
      <PricingSeo />
      {/* Same scroller contract as LandingPage: the sticky header sticks to this. */}
      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        <LandingHeader content={LANDING_CONTENT} />
        <Container component="main" maxWidth="lg" sx={{ py: RESPONSIVE.pricing.pagePaddingY }}>
          <Typography
            variant="h1"
            sx={{
              mb: RESPONSIVE.landingProto.sectionTitleMarginBottom,
              fontSize: RESPONSIVE.landingProto.heroHeadlineFontSize,
              fontWeight: 500,
              letterSpacing: '-0.03em',
              lineHeight: 1.08,
              maxWidth: 820,
              textWrap: 'balance',
            }}
          >
            {PRICING_CONTENT.title}
          </Typography>
          {notice && <PricingNotice notice={notice} />}
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
              gap: RESPONSIVE.pricing.cardGap,
              maxWidth: 880,
            }}
          >
            <FreePlanCard />
            <ProPlanCard
              cta={cta}
              busy={busy}
              authEnabled={authEnabled}
              onSignIn={onSignIn}
              onUpgrade={onUpgrade}
              onManage={onManage}
            />
          </Box>
        </Container>
      </Box>
    </Box>
  );
}
