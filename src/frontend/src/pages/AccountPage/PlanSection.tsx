import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import { Link as RouterLink } from 'react-router-dom';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import { useGetSubscriptionQuery } from '../../features/billing/billingApi';
import { useStripeRedirect } from '../../features/billing/useStripeRedirect';
import { describePlan } from './planView';

/** The /account Plan card, mounted only behind `BILLING_CONFIG.showAccountPlanCard`. */
export function PlanSection() {
  const { data, isLoading, isError } = useGetSubscriptionQuery();
  const { upgrade, manage, error, busy } = useStripeRedirect('Couldn’t open billing. Try again.');

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
            onClick={view.action === 'upgrade' ? upgrade : manage}
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
