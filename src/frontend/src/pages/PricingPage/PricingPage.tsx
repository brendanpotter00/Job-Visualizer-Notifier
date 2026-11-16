import { useCallback, useEffect, useRef, useState } from 'react';
import { Box, Container, Typography } from '@mui/material';
import { useSearchParams } from 'react-router-dom';
import { RESPONSIVE } from '../../config/responsive';
import { useAuth } from '../../features/auth/useAuth';
import { useGetSubscriptionQuery } from '../../features/billing/billingApi';
import { useStripeRedirect } from '../../features/billing/useStripeRedirect';
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
 * /pricing — Free vs Pro. Query params:
 * - `?intent=pro`        after "Sign in to upgrade": resume Checkout once
 * - `?checkout=success`  Stripe's success_url: poll until the webhook grants Pro
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
  const checkout = params.get('checkout');
  const intent = params.get('intent');

  const subscriptionQuery = useGetSubscriptionQuery(undefined, { skip: !isAuthenticated });
  const subscription = subscriptionQuery.data;
  const { refetch } = subscriptionQuery;

  const { upgrade, manage, error, busy } = useStripeRedirect(PRICING_CONTENT.notices.startFailed);

  const cta = resolveProCta({
    isAuthenticated,
    authLoading,
    subscription,
    subscriptionLoading: subscriptionQuery.isLoading,
    returnedFromCheckout: checkout === 'success',
  });

  // After Checkout: poll until the webhook lands, or give up after a minute.
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

  const onSignIn = useCallback(
    () => void loginWithReturnTo(PRICING_RESUME_PATH).catch(() => undefined),
    [loginWithReturnTo]
  );

  // Back from sign-in with ?intent=pro: resume Checkout exactly once.
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
    if (cta.kind === 'upgrade' && !cta.disabled) upgrade();
  }, [intent, cta, upgrade, setParams]);

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
        : null;

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
      {/* The sticky landing header sticks to this scroller, as on LandingPage. */}
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
              onUpgrade={upgrade}
              onManage={manage}
            />
          </Box>
        </Container>
      </Box>
    </Box>
  );
}
