import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import { Link as RouterLink } from 'react-router-dom';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import {
  goToStripe,
  useCreateCheckoutSessionMutation,
  useCreatePortalSessionMutation,
  useGetSubscriptionQuery,
} from '../../features/billing/billingApi';
import { extractErrorMessage } from '../../lib/errors';
import { describePlan } from './planView';

/**
 * The /account Plan card. Rendered only when `BILLING_CONFIG.showAccountPlanCard`
 * is on (default OFF — nothing to charge for yet); with it off this component is
 * never mounted, so /account makes no billing request at all.
 */
export function PlanSection() {
  const { data, isLoading, isError } = useGetSubscriptionQuery();
  const [startCheckout, checkoutState] = useCreateCheckoutSessionMutation();
  const [openPortal, portalState] = useCreatePortalSessionMutation();
  const [error, setError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  if (isError) return null; // billing is optional here; never break /account
  if (isLoading || !data) {
    return (
      <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg, mt: 3 }} aria-busy="true">
        <Skeleton width={48} />
        <Skeleton width="30%" height={40} />
      </Paper>
    );
  }

  const view = describePlan(data);
  const busy = redirecting || checkoutState.isLoading || portalState.isLoading;
  const run = async (request: () => Promise<{ url: string }>) => {
    setError(null);
    try {
      const { url } = await request();
      setRedirecting(true);
      goToStripe(url);
    } catch (err) {
      setError(extractErrorMessage(err, 'Couldn’t open billing. Try again.'));
    }
  };

  return (
    <Paper
      component="section"
      aria-label="Plan"
      sx={{ p: RESPONSIVE.spacing.paperPaddingLg, mt: 3 }}
    >
      <Typography variant="caption" color="text.secondary">
        Plan
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="h5" component="p">
          {view.plan}
        </Typography>
        {view.tag && <Chip size="small" variant="outlined" label={view.tag} />}
      </Box>
      <Typography
        variant="body2"
        color={view.danger ? 'error' : 'text.secondary'}
        sx={{ mt: 1, mb: view.action ? 2 : 0 }}
      >
        {view.line}
      </Typography>
      {error && (
        <Typography variant="body2" color="error" role="alert" sx={{ mb: 2 }}>
          {error}
        </Typography>
      )}
      {view.action && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <Button
            variant={view.action === 'upgrade' ? 'contained' : 'outlined'}
            disabled={busy || (view.action === 'upgrade' && !data.billingEnabled)}
            onClick={() =>
              void run(() =>
                view.action === 'upgrade' ? startCheckout().unwrap() : openPortal().unwrap()
              )
            }
            sx={{ borderRadius: 999, px: 2.5 }}
          >
            {view.actionLabel}
          </Button>
          {view.action === 'upgrade' && (
            <Button
              component={RouterLink}
              to={ROUTES.PRICING}
              variant="text"
              sx={{ color: 'text.primary' }}
            >
              Compare plans
            </Button>
          )}
        </Box>
      )}
    </Paper>
  );
}
