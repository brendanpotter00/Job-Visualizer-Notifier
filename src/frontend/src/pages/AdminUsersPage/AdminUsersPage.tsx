import { useMemo } from 'react';
import Container from '@mui/material/Container';
import Grid from '@mui/material/Grid';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { useGetAdminUsersStatsQuery, useListAdminUsersQuery } from '../../features/admin/adminApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { StatTile } from './components/StatTile';
import { ProviderBars } from './components/ProviderBars';
import { SignupTrendChart } from './components/SignupTrendChart';
import { UserRosterTable } from './components/UserRosterTable';

export function AdminUsersPage() {
  const usersQuery = useListAdminUsersQuery();
  const statsQuery = useGetAdminUsersStatsQuery();

  // Memoize the empty-array fallback so downstream useMemo identities stay
  // stable through the loading phase.
  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const stats = statsQuery.data;

  const createdAts = useMemo(() => users.map((u) => u.createdAt), [users]);

  const usersError = usersQuery.error;
  const statsError = statsQuery.error;

  // Per-slot loading semantics (audit pass-3 "Important" finding):
  //   - Page-level full spinner: only when BOTH queries are still loading
  //     AND neither has any data yet AND neither has errored. As soon as
  //     either side resolves or errors, we render the partial page so the
  //     loading slot doesn't mask the other slot's progress.
  //   - Each slot independently spins iff its own query is still loading
  //     and has no data yet. If a slot errors, it renders an inline error;
  //     if it has data, it renders normally.
  const usersSlotLoading = usersQuery.isLoading && users.length === 0;
  const statsSlotLoading = statsQuery.isLoading && !stats;
  const pageLevelLoading = usersSlotLoading && statsSlotLoading && !usersError && !statsError;

  if (pageLevelLoading) {
    return <LoadingState fullPage caption="Loading admin data…" />;
  }

  // Only fall back to the full-page error state when BOTH queries fail.
  // Single-query failures render an inline ErrorState in their own slot
  // so the rest of the page stays useful (audit log "Important" finding:
  // hiding the roster on a stats-only failure is the exact conflated-
  // failure pattern this PR is meant to prevent).
  if (usersError && statsError) {
    return (
      <Container maxWidth="xl" sx={{ py: 4 }}>
        <ErrorState
          inline
          message={extractErrorMessage(usersError ?? statsError, 'Failed to load admin data')}
          onRetry={() => {
            usersQuery.refetch();
            statsQuery.refetch();
          }}
        />
      </Container>
    );
  }

  // Header "X total" must reflect a TRUSTED stats number — never silently
  // fall back to ``users.length``. When stats errored AND we have no stats
  // payload, render an em-dash placeholder so the admin can see that the
  // total is unknown rather than reading the roster count as authoritative
  // (audit pass-3 "Important": ``stats?.totalUsers ?? users.length`` was
  // a silent fallback that hid a stats outage behind a plausible number).
  const statsUnavailable = Boolean(statsError) && !stats;
  const totalUsers = stats?.totalUsers ?? null;

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Admin · Users
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {statsUnavailable
          ? '— total'
          : totalUsers !== null
            ? `${totalUsers.toLocaleString()} total`
            : '— total'}
      </Typography>

      {statsError ? (
        // Stats failed in isolation — render an inline error in the stat
        // tile section but keep the roster below. Includes a retry that
        // only refetches the failed query.
        <ErrorState
          inline
          message={extractErrorMessage(statsError, 'Failed to load admin stats')}
          onRetry={() => statsQuery.refetch()}
        />
      ) : statsSlotLoading ? (
        // Stats query still pending while the roster has resolved — show
        // the stats-slot spinner so the admin sees explicit progress on
        // the half that hasn't loaded yet.
        <LoadingState minHeight={120} caption="Loading stats…" />
      ) : (
        <>
          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid size={{ xs: 12 }}>
              <StatTile
                label="Total users"
                value={totalUsers !== null ? totalUsers.toLocaleString() : '—'}
                meta="Cumulative signups"
              />
            </Grid>
          </Grid>

          <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
            <Typography variant="h6" component="h2" gutterBottom>
              Signups over time
            </Typography>
            <SignupTrendChart createdAts={createdAts} />
          </Paper>

          <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
            <Typography variant="h6" component="h2" gutterBottom>
              Signup providers
            </Typography>
            <ProviderBars data={stats?.byProvider ?? {}} />
          </Paper>
        </>
      )}

      {usersError ? (
        // Roster failed in isolation — render an inline error in the
        // roster slot. The stat tiles above still render.
        <ErrorState
          inline
          message={extractErrorMessage(usersError, 'Failed to load user roster')}
          onRetry={() => usersQuery.refetch()}
        />
      ) : usersSlotLoading ? (
        // Roster query still pending while stats has resolved (or
        // errored) — show the roster-slot spinner.
        <LoadingState minHeight={240} caption="Loading user roster…" />
      ) : (
        <UserRosterTable users={users} />
      )}
    </Container>
  );
}
