import { useMemo } from 'react';
import Container from '@mui/material/Container';
import Grid from '@mui/material/Grid';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import {
  useGetAdminUsersStatsQuery,
  useListAdminUsersQuery,
} from '../../features/admin/adminApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { StatTile } from './components/StatTile';
import { ProviderBars } from './components/ProviderBars';
import { SignupSparkline } from './components/SignupSparkline';
import { UserRosterTable } from './components/UserRosterTable';

function formatJoinedDate(iso: string | null): string {
  if (!iso) return '—';
  const idx = iso.indexOf('T');
  return idx > 0 ? iso.slice(0, idx) : iso;
}

function relativeDays(iso: string | null): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const diffMs = Date.now() - t;
  const days = Math.floor(diffMs / 86_400_000);
  if (days <= 0) {
    const hours = Math.max(0, Math.floor(diffMs / 3_600_000));
    if (hours <= 0) {
      const mins = Math.max(1, Math.floor(diffMs / 60_000));
      return `${mins}m ago`;
    }
    return `${hours}h ago`;
  }
  if (days === 1) return '1 day ago';
  return `${days} days ago`;
}

export function AdminUsersPage() {
  const usersQuery = useListAdminUsersQuery();
  const statsQuery = useGetAdminUsersStatsQuery();

  // Memoize the empty-array fallback so downstream useMemo identities stay
  // stable through the loading phase.
  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const stats = statsQuery.data;

  const createdAts = useMemo(() => users.map((u) => u.createdAt), [users]);

  const isLoading = usersQuery.isLoading || statsQuery.isLoading;
  const usersError = usersQuery.error;
  const statsError = statsQuery.error;
  // Page-level loading: only spin if BOTH queries are still pending. If
  // one resolves and the other errors, we'd rather show the partial page
  // with an error slot than keep the whole surface in loading limbo.
  if (isLoading && !stats && users.length === 0 && !usersError && !statsError) {
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
          message={extractErrorMessage(
            usersError ?? statsError,
            'Failed to load admin data'
          )}
          onRetry={() => {
            usersQuery.refetch();
            statsQuery.refetch();
          }}
        />
      </Container>
    );
  }

  const totalUsers = stats?.totalUsers ?? users.length;
  const firstSignup = stats?.firstSignupAt ?? null;
  const latestSignup = stats?.latestSignupAt ?? null;

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Admin · Users
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {totalUsers.toLocaleString()} total
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
      ) : (
        <>
          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid size={{ xs: 12, md: 4 }}>
              <StatTile
                label="Total users"
                value={totalUsers.toLocaleString()}
                meta="Cumulative signups"
                decoration={<SignupSparkline createdAts={createdAts} />}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 4 }}>
              <StatTile
                label="First signup"
                value={formatJoinedDate(firstSignup)}
                meta={firstSignup ? relativeDays(firstSignup) : '—'}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 4 }}>
              <StatTile
                label="Latest signup"
                value={formatJoinedDate(latestSignup)}
                meta={latestSignup ? relativeDays(latestSignup) : '—'}
              />
            </Grid>
          </Grid>

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
      ) : (
        <UserRosterTable users={users} />
      )}
    </Container>
  );
}
