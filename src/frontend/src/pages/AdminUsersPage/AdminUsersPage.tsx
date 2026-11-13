import { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import Grid from '@mui/material/Grid';
import Paper from '@mui/material/Paper';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import { useGetAdminUsersStatsQuery, useListAdminUsersQuery } from '../../features/admin/adminApi';
import { RESPONSIVE } from '../../config/responsive';
import { ChartSkeleton } from '../../components/shared/LoadingIndicator';
import {
  PageHeaderSkeleton,
  SectionSkeleton,
  SkeletonRegion,
  StatTilesSkeleton,
  TableSkeleton,
  TextSkeleton,
} from '../../components/shared/Skeletons';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { StatTile } from './components/StatTile';
import { ProviderBars } from './components/ProviderBars';
import { SignupTrendChart } from './components/SignupTrendChart';
import { SignupsPerDayChart } from './components/SignupsPerDayChart';
import { UserRosterTable } from './components/UserRosterTable';

type SignupChartTab = 'over-time' | 'per-day';

const ROSTER_COLUMNS = ['Email', 'Name', 'Joined', 'Visits', 'Last active', 'Provider', 'Admin', ''] as const;

const SIGNUP_CHART_HEIGHT = {
  xs: RESPONSIVE.adminChart.height.compact,
  sm: RESPONSIVE.adminChart.height.default,
} as const;

function StatsSlotSkeleton() {
  return (
    <>
      <StatTilesSkeleton count={1} size={{ xs: 12 }} sx={{ mb: 3 }} />
      <SectionSkeleton title="Signups">
        <ChartSkeleton height={SIGNUP_CHART_HEIGHT} />
      </SectionSkeleton>
      <SectionSkeleton title="Signup providers">
        <TextSkeleton lines={3} lastLineWidth="40%" />
      </SectionSkeleton>
    </>
  );
}

function RosterSlotSkeleton() {
  return (
    <TableSkeleton
      columns={ROSTER_COLUMNS}
      rows={6}
      title="User roster"
      toolbarControls={1}
      pagination
    />
  );
}

export function AdminUsersPage() {
  const usersQuery = useListAdminUsersQuery();
  const statsQuery = useGetAdminUsersStatsQuery();
  const [signupChartTab, setSignupChartTab] = useState<SignupChartTab>('over-time');

  // Memoize the empty-array fallback so downstream useMemo identities stay
  // stable through the loading phase.
  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const stats = statsQuery.data;

  const createdAts = useMemo(() => users.map((u) => u.createdAt), [users]);

  const usersError = usersQuery.error;
  const statsError = statsQuery.error;

  // Per-slot loading semantics (audit pass-3 "Important" finding):
  //   - Page-level skeleton: only when BOTH queries are still loading
  //     AND neither has any data yet AND neither has errored. As soon as
  //     either side resolves or errors, we render the partial page so the
  //     loading slot doesn't mask the other slot's progress.
  //   - Each slot independently shows its skeleton iff its own query is
  //     still loading and has no data yet. If a slot errors, it renders an
  //     inline error; if it has data, it renders normally.
  const usersSlotLoading = usersQuery.isLoading && users.length === 0;
  const statsSlotLoading = statsQuery.isLoading && !stats;
  const pageLevelLoading = usersSlotLoading && statsSlotLoading && !usersError && !statsError;

  if (pageLevelLoading) {
    return (
      <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        <SkeletonRegion label="Loading admin data…">
          <PageHeaderSkeleton title="Admin · Users" />
          <StatsSlotSkeleton />
          <RosterSlotSkeleton />
        </SkeletonRegion>
      </Container>
    );
  }

  // Only fall back to the full-page error state when BOTH queries fail.
  // Single-query failures render an inline ErrorState in their own slot
  // so the rest of the page stays useful (audit log "Important" finding:
  // hiding the roster on a stats-only failure is the exact conflated-
  // failure pattern this PR is meant to prevent).
  if (usersError && statsError) {
    return (
      <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
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
    <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
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
        // the stats-slot placeholder so the admin sees explicit progress on
        // the half that hasn't loaded yet.
        <SkeletonRegion label="Loading stats…">
          <StatsSlotSkeleton />
        </SkeletonRegion>
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

          <Paper variant="outlined" sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: 1,
                mb: 2,
              }}
            >
              <Typography variant="h6" component="h2">
                Signups
              </Typography>
              <Tabs
                value={signupChartTab}
                onChange={(_, value: SignupChartTab) => setSignupChartTab(value)}
                aria-label="Signups chart view"
              >
                <Tab value="over-time" label="Over time" />
                <Tab value="per-day" label="Per day" />
              </Tabs>
            </Box>
            {signupChartTab === 'over-time' ? (
              <SignupTrendChart createdAts={createdAts} />
            ) : (
              <SignupsPerDayChart createdAts={createdAts} />
            )}
          </Paper>

          <Paper variant="outlined" sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}>
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
        // errored) — show the roster-slot placeholder.
        <SkeletonRegion label="Loading user roster…">
          <RosterSlotSkeleton />
        </SkeletonRegion>
      ) : (
        <UserRosterTable users={users} />
      )}
    </Container>
  );
}
