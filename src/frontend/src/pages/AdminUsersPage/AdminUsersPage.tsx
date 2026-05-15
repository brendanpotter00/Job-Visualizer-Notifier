import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import { keyframes } from '@mui/system';
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
import { OPS, SX } from './adminUsersTheme';

const livePulse = keyframes`
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.45; transform: scale(0.78); }
`;

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

  // `usersQuery.data ?? []` creates a fresh empty array each render before
  // the fetch resolves; that array would invalidate every downstream useMemo
  // that depends on `users` on every render. Memoize so the identity is
  // stable across the loading phase.
  const users = useMemo(() => usersQuery.data ?? [], [usersQuery.data]);
  const stats = statsQuery.data;

  const createdAts = useMemo(() => users.map((u) => u.createdAt), [users]);

  const isLoading = usersQuery.isLoading || statsQuery.isLoading;
  const error = usersQuery.error ?? statsQuery.error;

  if (isLoading && !stats && users.length === 0) {
    return (
      <Box sx={SX.page}>
        <LoadingState fullPage caption="loading admin data..." />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={SX.page}>
        <ErrorState
          inline
          message={extractErrorMessage(error, 'Failed to load admin data')}
          onRetry={() => {
            usersQuery.refetch();
            statsQuery.refetch();
          }}
        />
      </Box>
    );
  }

  const totalUsers = stats?.totalUsers ?? users.length;
  const firstSignup = stats?.firstSignupAt ?? null;
  const latestSignup = stats?.latestSignupAt ?? null;

  return (
    <Box sx={SX.page}>
      {/* Header line — "ADMIN / USERS — n total" with pulsing live dot */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          mb: 4,
          flexWrap: 'wrap',
        }}
      >
        <Box
          sx={{
            width: 8,
            height: 8,
            bgcolor: OPS.accent,
            borderRadius: '50%',
            animation: `${livePulse} 1.6s ease-in-out infinite`,
          }}
        />
        <Box
          sx={{
            ...SX.caption,
            fontSize: 12,
            color: OPS.textPrimary,
            letterSpacing: '0.24em',
          }}
        >
          ADMIN&nbsp;&nbsp;/&nbsp;&nbsp;USERS
        </Box>
        <Box
          sx={{
            flexGrow: 1,
            height: 1,
            background: `linear-gradient(to right, ${OPS.border} 0, ${OPS.border} 60%, transparent 100%)`,
            mx: 1,
            display: { xs: 'none', sm: 'block' },
          }}
        />
        <Box
          sx={{
            fontFamily: OPS.mono,
            fontSize: 13,
            color: OPS.textMuted,
          }}
        >
          {totalUsers} total
        </Box>
      </Box>

      {/* Stat tiles */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 12, md: 4 }}>
          <StatTile
            label="TOTAL USERS"
            value={totalUsers.toLocaleString()}
            meta="cumulative signups"
            decoration={<SignupSparkline createdAts={createdAts} />}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 4 }}>
          <StatTile
            label="FIRST JOIN"
            value={formatJoinedDate(firstSignup)}
            meta={firstSignup ? relativeDays(firstSignup) : '—'}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 4 }}>
          <StatTile
            label="LATEST JOIN"
            value={formatJoinedDate(latestSignup)}
            meta={latestSignup ? relativeDays(latestSignup) : '—'}
          />
        </Grid>
      </Grid>

      {/* Provider breakdown */}
      <Box sx={{ ...SX.surface, p: 2.5, mb: 3 }}>
        <Box sx={{ ...SX.caption, mb: 2 }}>SIGNUP PROVIDER BREAKDOWN</Box>
        <ProviderBars data={stats?.byProvider ?? {}} />
      </Box>

      {/* User roster */}
      <UserRosterTable users={users} />

      {/* Footer line */}
      <Box
        sx={{
          mt: 3,
          pt: 2,
          borderTop: `1px dashed ${OPS.border}`,
          ...SX.dimMono,
          display: 'flex',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 1,
        }}
      >
        <span>read-only · live · {new Date().toISOString().slice(0, 19)}Z</span>
        <span>brendanpotter00@gmail.com — sole operator</span>
      </Box>
    </Box>
  );
}
