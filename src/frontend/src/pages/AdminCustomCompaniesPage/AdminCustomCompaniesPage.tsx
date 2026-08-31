import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Container from '@mui/material/Container';
import Grid from '@mui/material/Grid';
import InputAdornment from '@mui/material/InputAdornment';
import Paper from '@mui/material/Paper';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import RefreshIcon from '@mui/icons-material/Refresh';
import SearchIcon from '@mui/icons-material/Search';
import {
  adminApi,
  useGetAdminCustomCompaniesQuery,
  useGetAdminCustomCompanyAttemptsQuery,
  type AdminCustomCompaniesResponse,
  type AdminCustomCompanyAttemptsResponse,
  type AttemptOutcome,
} from '../../features/admin/adminApi';
import { useAppDispatch } from '../../app/hooks';
import { FacetSelect } from '../../components/shared/filters/FacetSelect';
import { EmptyState, ErrorState } from '../../components/shared/ErrorDisplay';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { RESPONSIVE } from '../../config/responsive';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { extractErrorMessage } from '../../lib/errors';
import type { FacetOption } from '../../types';
import { StatTile } from '../AdminUsersPage/components/StatTile';
import { AddAttemptsTable } from './components/AddAttemptsTable';
import { LiveScrapersTable } from './components/LiveScrapersTable';
import { UsersRollupTable } from './components/UsersRollupTable';
import { failedPercent } from './format';
import {
  ATTEMPT_OUTCOME_OPTIONS,
  HEALTH_STATE_OPTIONS,
  attemptOutcomeChip,
} from './statusChips';

/**
 * Admin oversight for user-added boards (E7 "custom companies"). Read-only:
 * four numbers and three tables answering four questions — what are users
 * adding, which users, which of those scrapers are actually live, and what
 * failed and why. There are deliberately no charts, no trends, and no admin
 * actions (no retry / quarantine / delete).
 *
 * Both endpoints are server-paginated and server-filtered; both also return
 * aggregates computed over the WHOLE table, so a filtered page never changes a
 * headline number. Every derived judgement ("is this live?", "is this attempt
 * stuck?") is made once in SQL and only rendered here — the page and its tiles
 * cannot drift apart because the page does not re-derive anything.
 *
 * Behind `AdminRoute` only, NOT behind `VITE_CUSTOM_COMPANIES_ENABLED`: the
 * environment where the user-facing flag is off is exactly the environment
 * where you most want to look at what the feature did.
 */
const DEFAULT_ROWS_PER_PAGE = 25;

/** "3 custom boards · 3 unverified" — non-zero health states, busiest first. */
function describeBoards(total: number, byHealthState: Record<string, number>): string {
  const boards = `${total.toLocaleString()} custom ${total === 1 ? 'board' : 'boards'}`;
  const parts = Object.entries(byHealthState)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    // '' is the key the backend uses for a NULL health_state — name it rather
    // than rendering a bare number with no noun.
    .map(([state, count]) => `${count.toLocaleString()} ${state === '' ? 'no health state' : state}`);
  return parts.length > 0 ? `${boards} · ${parts.join(', ')}` : boards;
}

/** "26 attempts · 17 added, 4 refused, 4 stuck, 1 already public". */
function describeAttempts(byOutcome: Partial<Record<AttemptOutcome, number>>): string {
  const total = Object.values(byOutcome).reduce((sum, n) => sum + n, 0);
  const head = `${total.toLocaleString()} ${total === 1 ? 'attempt' : 'attempts'}`;
  // Fixed order (the dropdown's), not payload order, so the sentence reads the
  // same on every refresh.
  const parts = ATTEMPT_OUTCOME_OPTIONS.map((option) => {
    const count = byOutcome[option.slug as AttemptOutcome] ?? 0;
    return count > 0 ? `${count.toLocaleString()} ${option.label}` : null;
  }).filter((part): part is string => part !== null);
  return parts.length > 0 ? `${head} · ${parts.join(', ')}` : head;
}

export function AdminCustomCompaniesPage() {
  const dispatch = useAppDispatch();

  // Table 1 controls.
  const [companiesPage, setCompaniesPage] = useState(0);
  const [companiesRowsPerPage, setCompaniesRowsPerPage] = useState(DEFAULT_ROWS_PER_PAGE);
  const [health, setHealth] = useState<string | undefined>(undefined);
  const [companiesSearch, setCompaniesSearch] = useState('');
  const debouncedCompaniesSearch = useDebouncedValue(companiesSearch, 300).trim();

  // Table 2 controls.
  const [attemptsPage, setAttemptsPage] = useState(0);
  const [attemptsRowsPerPage, setAttemptsRowsPerPage] = useState(DEFAULT_ROWS_PER_PAGE);
  const [outcome, setOutcome] = useState<AttemptOutcome | undefined>(undefined);
  const [userId, setUserId] = useState<string | undefined>(undefined);
  const [attemptsSearch, setAttemptsSearch] = useState('');
  const debouncedAttemptsSearch = useDebouncedValue(attemptsSearch, 300).trim();

  // Table 3 is paginated client-side — its payload arrives whole.
  const [usersPage, setUsersPage] = useState(0);
  const [usersRowsPerPage, setUsersRowsPerPage] = useState(DEFAULT_ROWS_PER_PAGE);

  // A filter change must land the reader on page 1 of the NEW result set, or
  // page 4 of a 2-page result renders empty. The debounced search terms cannot
  // be reset from an onChange, so both resets follow the same
  // adjust-state-during-render pattern AliasBrowser uses (React's documented
  // alternative to a reset effect).
  const companiesResetKey = `${health ?? ''}:${debouncedCompaniesSearch}`;
  const [lastCompaniesResetKey, setLastCompaniesResetKey] = useState(companiesResetKey);
  if (companiesResetKey !== lastCompaniesResetKey) {
    setLastCompaniesResetKey(companiesResetKey);
    setCompaniesPage(0);
  }

  const attemptsResetKey = `${outcome ?? ''}:${userId ?? ''}:${debouncedAttemptsSearch}`;
  const [lastAttemptsResetKey, setLastAttemptsResetKey] = useState(attemptsResetKey);
  if (attemptsResetKey !== lastAttemptsResetKey) {
    setLastAttemptsResetKey(attemptsResetKey);
    setAttemptsPage(0);
  }

  const companiesQuery = useGetAdminCustomCompaniesQuery({
    page: companiesPage,
    rowsPerPage: companiesRowsPerPage,
    health,
    search: debouncedCompaniesSearch || undefined,
  });
  const attemptsQuery = useGetAdminCustomCompanyAttemptsQuery({
    page: attemptsPage,
    rowsPerPage: attemptsRowsPerPage,
    outcome,
    userId,
    search: debouncedAttemptsSearch || undefined,
  });

  // Each (page, filters) tuple is a distinct RTK Query cache key, so ``data``
  // blips to undefined while the next page loads. Hold the last resolved
  // payload so paging and typing don't flash an empty table
  // (AdminFeedbackPage's trick).
  const [lastCompanies, setLastCompanies] = useState<AdminCustomCompaniesResponse>();
  if (companiesQuery.data && companiesQuery.data !== lastCompanies) {
    setLastCompanies(companiesQuery.data);
  }
  const [lastAttempts, setLastAttempts] = useState<AdminCustomCompanyAttemptsResponse>();
  if (attemptsQuery.data && attemptsQuery.data !== lastAttempts) {
    setLastAttempts(attemptsQuery.data);
  }

  const companiesData = companiesQuery.data ?? lastCompanies;
  const attemptsData = attemptsQuery.data ?? lastAttempts;
  const summary = companiesData?.summary;

  const handleRefresh = () => {
    dispatch(
      adminApi.util.invalidateTags(['AdminCustomCompanies', 'AdminCustomCompanyAttempts'])
    );
  };

  const header = (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 2,
        mb: 3,
      }}
    >
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          Admin · Custom Companies
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Boards users added themselves, and every attempt to add one.
        </Typography>
      </Box>
      <Button variant="outlined" startIcon={<RefreshIcon />} onClick={handleRefresh}>
        Refresh
      </Button>
    </Box>
  );

  // Full-page spinner only while BOTH reads are still in flight and neither has
  // ever resolved; afterwards each section owns its own state.
  if (
    companiesQuery.isLoading &&
    attemptsQuery.isLoading &&
    !lastCompanies &&
    !lastAttempts &&
    !companiesQuery.error &&
    !attemptsQuery.error
  ) {
    return <LoadingState fullPage caption="Loading custom companies…" />;
  }

  // Day one in production, and most days after: prod has none of the E7 tables,
  // so `schemaPresent` is false and every count is zero. Three empty tables
  // stacked would be miserable and a hard error would be wrong — nothing has
  // failed. The whole page collapses to one empty state until there is a single
  // attempt to show.
  const nothingToShow =
    companiesData !== undefined &&
    (!companiesData.schemaPresent ||
      (companiesData.summary.trackedCount === 0 && companiesData.summary.attemptCount === 0));

  if (nothingToShow) {
    return (
      <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        {header}
        <Paper variant="outlined" sx={{ p: RESPONSIVE.spacing.paperPadding }}>
          <EmptyState
            title="No one has added a company yet"
            message="Attempts appear here the moment a user pastes a careers URL — including the ones we refuse."
          />
        </Paper>
      </Container>
    );
  }

  const failedShare = summary ? failedPercent(summary.failedCount, summary.attemptCount) : null;

  // The User dropdown is fed from the UNFILTERED rollup, so selecting a user
  // never removes the other users from the list you selected them from.
  const userOptions: FacetOption[] = (attemptsData?.users ?? []).map((user, index) => ({
    slug: user.userId,
    label: user.email ?? user.displayName ?? user.userId,
    sortOrder: index,
  }));

  return (
    <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      {header}

      {/* The four questions as four numbers. */}
      {summary ? (
        <Grid container spacing={2} sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
          <Grid size={{ xs: 6, sm: 3 }}>
            <StatTile
              label="Live scrapers"
              value={summary.liveCount.toLocaleString()}
              meta={`of ${summary.trackedCount.toLocaleString()} tracked`}
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 3 }}>
            <StatTile
              label="Add attempts"
              value={summary.attemptCount.toLocaleString()}
              meta="all time"
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 3 }}>
            <StatTile
              label="Failed"
              value={summary.failedCount.toLocaleString()}
              meta={`${summary.refusedCount.toLocaleString()} refused · ${summary.stuckCount.toLocaleString()} stuck`}
              decoration={
                failedShare === null ? undefined : (
                  <Chip size="small" color="error" label={`${failedShare}%`} />
                )
              }
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 3 }}>
            <StatTile
              label="Users"
              value={summary.userCount.toLocaleString()}
              meta="has ever added one"
            />
          </Grid>
        </Grid>
      ) : companiesQuery.error ? (
        <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
          <ErrorState
            inline
            message={extractErrorMessage(companiesQuery.error, 'Failed to load custom companies')}
            onRetry={() => companiesQuery.refetch()}
          />
        </Box>
      ) : (
        <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
          <LoadingState minHeight={120} caption="Loading headline counts…" />
        </Box>
      )}

      {/* ── Table 1 — which custom scrapers are actually live ───────────── */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2">
          Live scrapers
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {summary
            ? describeBoards(summary.trackedCount, summary.byHealthState)
            : 'Boards users added themselves.'}
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
          <FacetSelect
            label="Health"
            options={HEALTH_STATE_OPTIONS}
            value={health}
            onChange={setHealth}
          />
          <TextField
            value={companiesSearch}
            onChange={(e) => setCompaniesSearch(e.target.value)}
            placeholder="Search company or owner"
            size="small"
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" color="action" />
                  </InputAdornment>
                ),
              },
            }}
            sx={{ minWidth: 170, width: { xs: '100%', sm: 280 } }}
          />
        </Box>
        {companiesQuery.error && !companiesData ? (
          <ErrorState
            inline
            message={extractErrorMessage(companiesQuery.error, 'Failed to load custom companies')}
            onRetry={() => companiesQuery.refetch()}
          />
        ) : !companiesData ? (
          <LoadingState minHeight={120} caption="Loading boards…" />
        ) : (
          <LiveScrapersTable
            companies={companiesData.companies}
            total={companiesData.total}
            page={companiesPage}
            rowsPerPage={companiesRowsPerPage}
            onPageChange={setCompaniesPage}
            onRowsPerPageChange={(next) => {
              setCompaniesRowsPerPage(next);
              setCompaniesPage(0);
            }}
          />
        )}
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          <strong>Live</strong> means enabled, the newest harvest was not FAILED, it returned
          more than zero records, and it ran inside twice its cadence — not merely that a
          harvest row exists. <strong>Orphan</strong> is a board with no owner row at all.
        </Typography>
      </Paper>

      {/* ── Table 2 — what users are adding, and what failed ────────────── */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2">
          Add attempts
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {attemptsData
            ? describeAttempts(attemptsData.byOutcome)
            : 'Every attempt to add a board, including the ones we refuse.'}
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
          <FacetSelect
            label="Outcome"
            options={ATTEMPT_OUTCOME_OPTIONS}
            value={outcome}
            onChange={(slug) => setOutcome(slug as AttemptOutcome | undefined)}
          />
          <FacetSelect label="User" options={userOptions} value={userId} onChange={setUserId} />
          <TextField
            value={attemptsSearch}
            onChange={(e) => setAttemptsSearch(e.target.value)}
            placeholder="Search URL"
            size="small"
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" color="action" />
                  </InputAdornment>
                ),
              },
            }}
            sx={{ minWidth: 170, width: { xs: '100%', sm: 280 } }}
          />
        </Box>
        {attemptsQuery.error && !attemptsData ? (
          <ErrorState
            inline
            message={extractErrorMessage(attemptsQuery.error, 'Failed to load add attempts')}
            onRetry={() => attemptsQuery.refetch()}
          />
        ) : !attemptsData ? (
          <LoadingState minHeight={120} caption="Loading attempts…" />
        ) : (
          <AddAttemptsTable
            attempts={attemptsData.attempts}
            total={attemptsData.total}
            page={attemptsPage}
            rowsPerPage={attemptsRowsPerPage}
            onPageChange={setAttemptsPage}
            onRowsPerPageChange={(next) => {
              setAttemptsRowsPerPage(next);
              setAttemptsPage(0);
            }}
          />
        )}
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          One row per <em>attempt</em>, not per audit row — a discovery writes an interim
          row and then a terminal one, and this is the terminal one.{' '}
          <strong>{attemptOutcomeChip('stuck').label}</strong> means the newest row is still{' '}
          <code>discovery_pending</code> past the sweeper's grace period; there is no such
          value in the database.
        </Typography>
      </Paper>

      {/* ── Table 3 — which users ───────────────────────────────────────── */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2">
          Users
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Who is actually using this. Always counted over every attempt, never the filters
          above.
        </Typography>
        {attemptsQuery.error && !attemptsData ? (
          <ErrorState
            inline
            message={extractErrorMessage(attemptsQuery.error, 'Failed to load the user rollup')}
            onRetry={() => attemptsQuery.refetch()}
          />
        ) : !attemptsData ? (
          <LoadingState minHeight={120} caption="Loading users…" />
        ) : (
          <UsersRollupTable
            users={attemptsData.users}
            usersTruncated={attemptsData.usersTruncated}
            page={usersPage}
            rowsPerPage={usersRowsPerPage}
            onPageChange={setUsersPage}
            onRowsPerPageChange={(next) => {
              setUsersRowsPerPage(next);
              setUsersPage(0);
            }}
          />
        )}
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          <strong>Owns now</strong> differs from <strong>Added</strong> because deleting a
          custom company hard-deletes its row — the audit log is the only thing that still
          remembers those boards.
        </Typography>
      </Paper>
    </Container>
  );
}
