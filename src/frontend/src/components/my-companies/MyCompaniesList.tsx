import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { LoadingState } from '../shared/LoadingIndicator';
import { ErrorState, EmptyState } from '../shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { buildMyCompanyDetailPath } from '../../config/routes';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import {
  useGetUserCompaniesQuery,
  useRemoveUserCompanyMutation,
  type UserCompany,
} from '../../features/userCompanies/userCompaniesApi';
import {
  describeHealthState,
  describeLastChecked,
  shouldShowDiscovery,
} from './companyHealth';
import { DiscoveryChecklist } from './DiscoveryChecklist';

/** Poll cadence while any row is still an empty, unverified board. */
const POLL_INTERVAL_MS = 15_000;

/**
 * Faster cadence while a one-time discovery is actually running. Its four steps take
 * seconds each, so a 15s poll would show a checklist that jumps two rungs at a time and
 * is usually already stale — the same opaque wait the checklist exists to remove. Still
 * the SAME query and the same component (DECISION D2: extend the existing poll, never
 * add a second channel); only the interval changes, and only while a row is
 * `discovering`, which is a bounded few minutes per board.
 */
const DISCOVERY_POLL_INTERVAL_MS = 4_000;

/**
 * A row is "still settling" if its first harvest hasn't landed yet, so the list
 * should keep polling for it. Two cases:
 *  - `discovering` — the one-time capture setup is still running (E7 capture
 *    pivot); the row flips to tracked or `refused` when it finishes.
 *  - `unverified` with no jobs yet — a brand-new tracked board whose first
 *    harvest hasn't run.
 */
function isStillSettling(company: UserCompany): boolean {
  return (
    company.healthState === 'discovering' ||
    (company.healthState === 'unverified' && company.openJobCount === 0)
  );
}

/**
 * How often to re-poll, given the rows we have: nothing while everything is settled,
 * the fast cadence while a discovery is mid-run, the slow one otherwise.
 *
 * Pure, and computed from the rows rather than held in state, so `CompaniesPoller`
 * stays a plain-prop component (see below).
 */
function pollIntervalFor(rows: UserCompany[]): number {
  if (
    CUSTOM_COMPANIES_CONFIG.isDiscoveryProgressEnabled &&
    rows.some((company) => company.healthState === 'discovering')
  ) {
    return DISCOVERY_POLL_INTERVAL_MS;
  }
  return rows.some(isStillSettling) ? POLL_INTERVAL_MS : 0;
}

/**
 * Adds (only) a polling subscription to the shared `getUserCompanies` cache at
 * `intervalMs` (0 = off). Split into its own component so the poll cadence is
 * derived from a plain prop — no effect, no setState-in-render, no ref-in-render
 * (all three are lint-blocked). Both this and the list subscribe to the same
 * query key; RTK Query merges them and polls at this subscriber's interval.
 */
function CompaniesPoller({ intervalMs }: { intervalMs: number }) {
  useGetUserCompaniesQuery(undefined, { pollingInterval: intervalMs });
  return null;
}

/** One company row: name → trend page, health badge, count, last-checked, remove. */
function CompanyRow({
  company,
  onRemove,
}: {
  company: UserCompany;
  onRemove: (company: UserCompany) => void;
}) {
  const badge = describeHealthState(company.healthState);
  // Flag OFF must render byte-for-byte what shipped before the checklist existed, so
  // the gate is here rather than inside the component: no extra element, no wrapper.
  const showChecklist =
    CUSTOM_COMPANIES_CONFIG.isDiscoveryProgressEnabled && shouldShowDiscovery(company);
  return (
    <Paper variant="outlined" sx={{ p: 2 }} data-testid="my-company-row">
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1.5}
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        justifyContent="space-between"
      >
        <Box sx={{ minWidth: 0 }}>
          <Link
            component={RouterLink}
            to={buildMyCompanyDetailPath(company.id)}
            variant="h6"
            data-testid="my-company-link"
          >
            {company.displayName}
          </Link>
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            flexWrap="wrap"
            useFlexGap
            sx={{ mt: 0.5 }}
          >
            <Chip size="small" color={badge.color} label={badge.label} />
            <Typography variant="body2" color="text.secondary">
              {company.openJobCount.toLocaleString()}{' '}
              {company.openJobCount === 1 ? 'open job' : 'open jobs'}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {describeLastChecked(company)}
            </Typography>
          </Stack>
        </Box>

        <Button
          color="error"
          size="small"
          onClick={() => onRemove(company)}
          data-testid="my-company-remove"
        >
          Remove
        </Button>
      </Stack>

      {showChecklist && <DiscoveryChecklist company={company} />}
    </Paper>
  );
}

/**
 * The signed-in user's tracked companies, rendered below the resolve form.
 *
 * Only mounted behind the feature flag (its parent page is route-gated), so it
 * makes no network call in a flag-off build. Polls `getUserCompanies` every 15s
 * *only* while some row is an empty unverified board — a brand-new add whose
 * first harvest hasn't landed yet — and stops as soon as every row has jobs or
 * leaves the unverified state, so a settled list is not polled forever.
 */
export function MyCompaniesList() {
  const { data: companies, isLoading, isError, error, refetch } = useGetUserCompaniesQuery();

  const [removeUserCompany] = useRemoveUserCompanyMutation();
  const [pendingRemoval, setPendingRemoval] = useState<UserCompany | null>(null);

  const confirmRemoval = () => {
    if (pendingRemoval) {
      void removeUserCompany(pendingRemoval.id);
    }
    setPendingRemoval(null);
  };

  if (isLoading) {
    return <LoadingState minHeight={120} caption="Loading your companies…" />;
  }

  if (isError) {
    return (
      <ErrorState
        inline
        message={extractErrorMessage(error, "We couldn't load your companies.")}
        onRetry={() => void refetch()}
      />
    );
  }

  const rows = companies ?? [];

  return (
    <Box>
      {/* Auto-refresh while any brand-new board hasn't reported jobs yet — faster
          while a discovery is mid-run so its checklist reads as live. */}
      <CompaniesPoller intervalMs={pollIntervalFor(rows)} />

      <Typography variant="h6" component="h2" gutterBottom>
        Companies you&apos;re tracking
      </Typography>

      {rows.length === 0 ? (
        <EmptyState
          title="No companies yet"
          message="Check a careers URL above, then choose “Track this company” to start building its hiring history."
        />
      ) : (
        <Stack spacing={1.5} data-testid="my-companies-list">
          {rows.map((company) => (
            <CompanyRow key={company.id} company={company} onRemove={setPendingRemoval} />
          ))}
        </Stack>
      )}

      <Dialog open={pendingRemoval !== null} onClose={() => setPendingRemoval(null)}>
        <DialogTitle>Stop tracking this company?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {pendingRemoval
              ? `“${pendingRemoval.displayName}” will be removed from your account and its hiring history will no longer be collected for you.`
              : ''}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingRemoval(null)}>Cancel</Button>
          <Button color="error" onClick={confirmRemoval} data-testid="my-company-remove-confirm">
            Remove
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
