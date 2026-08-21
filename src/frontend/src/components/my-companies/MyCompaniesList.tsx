import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
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
 * How stale a `discovering` row's last progress write may be before we stop believing
 * anything is still running behind it.
 *
 * A row only leaves `discovering` when the task persists an outcome, and that task is
 * `retry=1`. Three documented paths leave it there for good: the discovery flag flipped
 * off between enqueue and execution, no worker draining the `custom_discovery` queue, and
 * the SIGKILL/OOM "WEDGED-ROW CAVEAT" the task itself carries a TODO for. Without a bound,
 * such a row would poll every 4s for as long as the tab stays open — ~900 requests/hour,
 * each running a per-row `count(*)` — while the user watches a checklist frozen mid-step.
 * Past this window the row falls back to the ordinary 15s settling cadence, so a wedged
 * row costs no more than it did before the checklist existed. Comfortably above the task's
 * own 240s cap, because a run whose progress writes are all failing still updates nothing
 * until it terminates — and being slow there is a cadence choice, not a correctness one.
 */
const DISCOVERY_STALE_AFTER_MS = 5 * 60_000;

/**
 * Is this row a discovery we have recent evidence is still moving?
 *
 * `discovery.updatedAt` is stamped by every progress write, which is exactly the signal
 * the backend emits it for. A missing or unparseable timestamp reads as NOT live (an
 * older blob shouldn't buy the fast cadence); a timestamp in the future does read as live,
 * since that is clock skew between the server and this browser, not staleness.
 *
 * `receivedAt` is RTK Query's `fulfilledTimeStamp`, NOT `Date.now()`: reading the clock
 * during render is lint-blocked as impure, and "how stale was this row when the payload
 * carrying it arrived" is the more honest question anyway. It advances on every poll, so
 * a run that stops writing ages out on its own.
 */
function isDiscoveryLive(company: UserCompany, receivedAt: number): boolean {
  if (company.healthState !== 'discovering') return false;
  const updatedAt = company.discovery?.updatedAt;
  if (!updatedAt) return false;
  const writtenAt = Date.parse(updatedAt);
  if (Number.isNaN(writtenAt)) return false;
  return writtenAt >= receivedAt - DISCOVERY_STALE_AFTER_MS;
}

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
 * the fast cadence while a discovery is demonstrably mid-run, the slow one otherwise.
 *
 * Pure — `receivedAt` is passed in rather than read from the clock — and computed from
 * the rows rather than held in state, so `CompaniesPoller` stays a plain-prop component
 * (see below). Re-evaluated on every render, so a run that goes quiet drops itself to
 * the slow cadence on the next poll without anything having to notice.
 */
function pollIntervalFor(rows: UserCompany[], receivedAt: number): number {
  if (
    CUSTOM_COMPANIES_CONFIG.isDiscoveryProgressEnabled &&
    rows.some((company) => isDiscoveryLive(company, receivedAt))
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
 * leaves the unverified state, so a settled list is not polled forever. A
 * discovery whose progress blob is still moving gets the faster cadence instead
 * (see `pollIntervalFor`), bounded by staleness so a wedged row cannot hold it.
 */
export function MyCompaniesList() {
  const {
    data: companies,
    isLoading,
    isError,
    error,
    refetch,
    // When the payload we are rendering actually landed. Stands in for `Date.now()`,
    // which cannot be read during render — see `isDiscoveryLive`.
    fulfilledTimeStamp,
  } = useGetUserCompaniesQuery();

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

  // ONLY when there is nothing to show. RTK Query keeps `data` from the last good fetch
  // and still flips the entry to rejected, so taking this branch on every `isError` let
  // one transient 502 on a *poll* delete every row — and unmount `CompaniesPoller` with
  // them, so auto-refresh never resumed without a manual Retry. That lands hardest on a
  // mid-run discovery, the one screen whose entire point is being live.
  if (isError && !companies) {
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
      <CompaniesPoller intervalMs={pollIntervalFor(rows, fulfilledTimeStamp ?? 0)} />

      {/* A failed refresh over a list we already have: say so, keep the list, keep
          polling. The next tick usually fixes it without the user doing anything. */}
      {isError ? (
        <Alert
          severity="warning"
          sx={{ mb: 1.5 }}
          data-testid="my-companies-refresh-warning"
          action={
            <Button color="inherit" size="small" onClick={() => void refetch()}>
              Retry
            </Button>
          }
        >
          We couldn&apos;t refresh just now — showing what we last loaded.
        </Alert>
      ) : null}

      <Typography variant="h6" component="h2" gutterBottom>
        Companies you&apos;re tracking
      </Typography>

      {rows.length === 0 ? (
        <EmptyState
          title="No companies yet"
          // Names the ONE action, not the branch it might take. The old copy told the
          // user to press "Track this company" — a button that never appears on the
          // discovery path, which is the path anything not on a supported board takes.
          message="Paste a careers URL above to start tracking a company."
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
