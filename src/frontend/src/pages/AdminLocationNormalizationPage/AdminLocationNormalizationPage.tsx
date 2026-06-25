import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import RefreshIcon from '@mui/icons-material/Refresh';
import {
  adminApi,
  useGetLocationHealthQuery,
  useGetLocationIntegrityQuery,
  type AliasRow,
} from '../../features/admin/adminApi';
import { useAppDispatch } from '../../app/hooks';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { RESPONSIVE } from '../../config/responsive';
import { computeVerdict } from './verdict';
import { HealthOverview } from './components/HealthOverview';
import { IntegrityTable } from './components/IntegrityTable';
import { AliasBrowser } from './components/AliasBrowser';
import { AliasEditDialog } from './components/AliasEditDialog';
import { ProblemJobsTable } from './components/ProblemJobsTable';

export function AdminLocationNormalizationPage() {
  const dispatch = useAppDispatch();
  const healthQuery = useGetLocationHealthQuery();
  const integrityQuery = useGetLocationIntegrityQuery();

  const [editAlias, setEditAlias] = useState<AliasRow | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const health = healthQuery.data;
  const integrity = integrityQuery.data;

  const healthError = healthQuery.error;
  const integrityError = integrityQuery.error;

  // Per-slot loading semantics (cloned from AdminUsersPage): the full-page
  // spinner shows only when BOTH the health and integrity reads are still
  // loading with no data and no error. As soon as either resolves or errors,
  // render the partial page so each section can show its own state.
  const healthSlotLoading = healthQuery.isLoading && !health;
  const integritySlotLoading = integrityQuery.isLoading && !integrity;
  const pageLevelLoading =
    healthSlotLoading && integritySlotLoading && !healthError && !integrityError;

  const handleRefresh = () => {
    healthQuery.refetch();
    integrityQuery.refetch();
    // The problem-jobs table owns its own pagination, so refetch it by TAG
    // rather than a query-instance refetch pinned to offset 0 — this refreshes
    // whatever page the table is currently showing.
    dispatch(adminApi.util.invalidateTags(['LocationProblemJobs']));
  };

  const handleEdit = (alias: AliasRow) => {
    setEditAlias(alias);
    setEditOpen(true);
  };

  if (pageLevelLoading) {
    return <LoadingState fullPage caption="Loading location normalization data…" />;
  }

  // The verdict is the focal element. It is derived ONLY from a trusted
  // health+integrity pair — never from partial data. If either query is
  // missing or errored, we render a neutral "verdict unknown" state rather
  // than fabricating a HEALTHY verdict from half the inputs.
  const verdict = health && integrity ? computeVerdict(health, integrity) : null;

  return (
    <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
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
            Admin · Location Normalization
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Health, integrity invariants, and the alias cache for location normalization.
          </Typography>
        </Box>
        <Button variant="outlined" startIcon={<RefreshIcon />} onClick={handleRefresh}>
          Refresh
        </Button>
      </Box>

      {/* 1. Verdict banner — the focal element. */}
      {verdict ? (
        <Paper
          variant="outlined"
          sx={{
            p: 2.5,
            mb: RESPONSIVE.spacing.sectionMarginB,
            borderLeft: 6,
            borderLeftColor: `${verdict.color}.main`,
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', mb: 1 }}>
            <Chip label={verdict.verdict} color={verdict.color} />
            <Typography variant="h6" component="p">
              {verdict.summary}
            </Typography>
          </Box>
          {health && (
            <Typography variant="body2" color="text.secondary">
              {health.heartbeatAgeMinutes !== null
                ? `Heartbeat ${Math.round(health.heartbeatAgeMinutes)}m ago`
                : 'Heartbeat: none'}
              {' · '}
              {health.keyConfigured ? 'LLM key configured' : 'LLM key missing'}
              {' · '}
              {health.throughputInWindow !== null
                ? `${health.throughputInWindow.toLocaleString()} normalized / ${health.windowHours}h`
                : `throughput unknown / ${health.windowHours}h`}
            </Typography>
          )}
        </Paper>
      ) : (
        <Paper
          variant="outlined"
          sx={{
            p: 2.5,
            mb: RESPONSIVE.spacing.sectionMarginB,
            borderLeft: 6,
            borderLeftColor: 'text.disabled',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <Chip label="VERDICT UNKNOWN" variant="outlined" />
            <Typography variant="h6" component="p" color="text.secondary">
              Verdict unavailable — health or integrity data could not be loaded.
            </Typography>
          </Box>
        </Paper>
      )}

      {/* 2. Health overview. */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2" gutterBottom>
          Health overview
        </Typography>
        {healthError ? (
          <ErrorState
            inline
            message={extractErrorMessage(healthError, 'Failed to load health')}
            onRetry={() => healthQuery.refetch()}
          />
        ) : healthSlotLoading ? (
          <LoadingState minHeight={160} caption="Loading health…" />
        ) : health ? (
          <HealthOverview health={health} />
        ) : null}
      </Paper>

      {/* 3. Integrity invariants. */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2" gutterBottom>
          Integrity invariants
        </Typography>
        {integrityError ? (
          <ErrorState
            inline
            message={extractErrorMessage(integrityError, 'Failed to load integrity checks')}
            onRetry={() => integrityQuery.refetch()}
          />
        ) : integritySlotLoading ? (
          <LoadingState minHeight={160} caption="Loading integrity checks…" />
        ) : integrity ? (
          <IntegrityTable checks={integrity} />
        ) : null}
      </Paper>

      {/* 4. Alias cache browser (self-contained — owns its own queries/state). */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2" gutterBottom>
          Alias cache browser
        </Typography>
        <AliasBrowser onEdit={handleEdit} />
      </Paper>

      {/* 6. Problem jobs (self-contained). */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2" gutterBottom>
          Problem jobs
        </Typography>
        <ProblemJobsTable />
      </Paper>

      {/* 5. Edit dialog (opened from a forward alias row). */}
      <AliasEditDialog open={editOpen} alias={editAlias} onClose={() => setEditOpen(false)} />
    </Container>
  );
}
