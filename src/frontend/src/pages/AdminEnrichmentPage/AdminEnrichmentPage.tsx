import { useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Container from '@mui/material/Container';
import Grid from '@mui/material/Grid';
import FormControlLabel from '@mui/material/FormControlLabel';
import Paper from '@mui/material/Paper';
import Switch from '@mui/material/Switch';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import RefreshIcon from '@mui/icons-material/Refresh';
import {
  adminApi,
  useGetAdminSettingsQuery,
  useGetEnrichmentHealthQuery,
  useGetEnrichmentTicksQuery,
  useUpdateAdminSettingMutation,
} from '../../features/admin/adminApi';
import { useAppDispatch } from '../../app/hooks';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { RESPONSIVE } from '../../config/responsive';
import { StatTile } from '../AdminUsersPage/components/StatTile';
import { computeEnrichmentVerdict, formatAge } from './verdict';
import { PipelineFunnel } from './components/PipelineFunnel';
import { TickStrip } from './components/TickStrip';
import { TickCharts } from './components/TickCharts';
import { ScorecardPanel } from './components/ScorecardPanel';
import { NeedsHumanTable } from './components/NeedsHumanTable';
import { RecentEnrichmentsTable } from './components/RecentEnrichmentsTable';

/**
 * Admin oversight for the external-enrichment pull pipeline. The pull model's
 * contract is that JVN never depends on the laptop being up — which means JVN
 * must be able to SEE when it isn't. This page is that seeing: a verdict
 * banner (is it alive?), the backlog funnel (is work moving?), the tick EKG +
 * charts (how is each cycle behaving?), eval quality (should I trust the
 * labels?), and the needs-human queue (what does the agent want ME to decide?).
 */
/**
 * The reveal threshold, DISPLAYED and never enforced.
 *
 * ⚠ The switch is flipped BY HAND. There is deliberately no auto-reveal: a
 * filter that switches itself on mid-session is surprising, and a coverage
 * number hovering near the line would flap the UI on and off. The frontend
 * reads only a boolean; this constant exists so the operator can see how close
 * they are.
 */
const REVEAL_THRESHOLD_PCT = 90;

const SWE_SUBCATEGORIES_KEY = 'swe_subcategories_enabled';

export function AdminEnrichmentPage() {
  const dispatch = useAppDispatch();
  const [windowHours, setWindowHours] = useState(24);
  const [settingError, setSettingError] = useState<string | null>(null);

  const settingsQuery = useGetAdminSettingsQuery();
  const [updateSetting, { isLoading: savingSetting }] = useUpdateAdminSettingMutation();
  const revealRow = settingsQuery.data?.find((row) => row.key === SWE_SUBCATEGORIES_KEY);
  const revealEnabled = revealRow?.value === true;

  const handleRevealToggle = async (next: boolean) => {
    setSettingError(null);
    try {
      await updateSetting({ key: SWE_SUBCATEGORIES_KEY, value: next }).unwrap();
    } catch (err) {
      setSettingError(extractErrorMessage(err, 'Failed to update the rollout flag'));
    }
  };

  const healthQuery = useGetEnrichmentHealthQuery({ windowHours });
  const ticksQuery = useGetEnrichmentTicksQuery({ windowHours });

  const health = healthQuery.data;
  const ticks = ticksQuery.data;

  // Per-slot loading semantics (AdminLocationNormalizationPage pattern): the
  // full-page spinner shows only while BOTH top reads are pending; afterwards
  // each section renders its own state.
  const healthSlotLoading = healthQuery.isLoading && !health;
  const ticksSlotLoading = ticksQuery.isLoading && !ticks;
  if (healthSlotLoading && ticksSlotLoading && !healthQuery.error && !ticksQuery.error) {
    return <LoadingState fullPage caption="Loading enrichment pipeline…" />;
  }

  const verdict = health ? computeEnrichmentVerdict(health) : null;

  const handleRefresh = () => {
    healthQuery.refetch();
    ticksQuery.refetch();
    // The queue + recent tables own their queries; refresh via tags so
    // whatever page/filter they're on reloads in place.
    dispatch(
      adminApi.util.invalidateTags([
        'EnrichmentNeedsHuman',
        'EnrichmentRecent',
        'AdminSettings',
      ])
    );
  };

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
            Admin · Enrichment Pipeline
          </Typography>
          <Typography variant="body2" color="text.secondary">
            The laptop-side Claude agent that classifies jobs (category · level · tags), its
            liveness, quality, and the queue of rows waiting on a human.
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center' }}>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={windowHours}
            onChange={(_e, v: number | null) => {
              if (v !== null) setWindowHours(v);
            }}
            aria-label="Metrics window"
          >
            <ToggleButton value={24}>24h</ToggleButton>
            <ToggleButton value={72}>3d</ToggleButton>
            <ToggleButton value={168}>7d</ToggleButton>
          </ToggleButtonGroup>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={handleRefresh}>
            Refresh
          </Button>
        </Box>
      </Box>

      {/* 1. Verdict banner — the focal element (family style: left border + chip). */}
      {verdict && health ? (
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
          <Typography variant="body2" color="text.secondary">
            {health.lastTickAgeS !== null
              ? `Last tick ${formatAge(health.lastTickAgeS)} ago (${health.lastTickStatus})`
              : 'No ticks pushed yet'}
            {' · '}
            {health.lastEnrichedAgeS !== null
              ? `last write ${formatAge(health.lastEnrichedAgeS)} ago`
              : 'no writes yet'}
            {' · '}
            claim TTL {health.claimTtlMinutes}m
          </Typography>
          {verdict.notes.length > 0 && (
            <Box sx={{ mt: 1 }}>
              {verdict.notes.map((note) => (
                <Typography key={note} variant="body2" color="text.secondary">
                  • {note}
                </Typography>
              ))}
            </Box>
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
          {healthQuery.error ? (
            <ErrorState
              inline
              message={extractErrorMessage(healthQuery.error, 'Failed to load pipeline health')}
              onRetry={() => healthQuery.refetch()}
            />
          ) : (
            <LoadingState minHeight={48} caption="Loading health…" />
          )}
        </Paper>
      )}

      {/* 2. Backlog funnel + key stats. */}
      {health && (
        <Paper
          variant="outlined"
          sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
        >
          <Typography variant="h6" component="h2" gutterBottom>
            Backlog funnel
          </Typography>
          <PipelineFunnel health={health} />
          <Grid container spacing={2} sx={{ mt: 1.5 }}>
            <Grid size={{ xs: 6, sm: 3 }}>
              <StatTile
                label={`Enriched / ${health.windowHours}h`}
                value={health.enrichedInWindow.toLocaleString()}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 3 }}>
              <StatTile
                label="Needs human (open)"
                value={health.needsHumanOpen.toLocaleString()}
                meta={`${health.humanCorrectedTotal.toLocaleString()} corrected all-time`}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 3 }}>
              <StatTile
                label="Stale claims"
                value={health.staleClaims.toLocaleString()}
                meta={`TTL ${health.claimTtlMinutes}m`}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 3 }}>
              <StatTile
                label={`Error ticks / ${health.windowHours}h`}
                value={health.errorTicksInWindow.toLocaleString()}
              />
            </Grid>
          </Grid>
        </Paper>
      )}

      {/* 2b. Subcategory rollout: the number you are watching and the switch
              you throw, deliberately side by side. Reading coverage on one
              screen and flipping the flag on another is how a flag gets turned
              on at the wrong number. */}
      {health && (
        <Paper
          variant="outlined"
          sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
        >
          <Typography variant="h6" component="h2" gutterBottom>
            Subcategory rollout
          </Typography>
          <Grid container spacing={2} alignItems="flex-start">
            <Grid size={{ xs: 12, sm: 6 }}>
              <StatTile
                label="OPEN SWE coverage"
                value={
                  // ⚠ Guard the divide. `sweOpenTotal: 0` is the state of a
                  // pre-migration or empty database, and NaN% on the admin page
                  // is worse than an em dash.
                  health.sweOpenTotal > 0
                    ? `${((health.sweSubcategorized / health.sweOpenTotal) * 100).toFixed(1)}%`
                    : '—'
                }
                meta={
                  health.sweOpenTotal > 0
                    ? `${health.sweSubcategorized.toLocaleString()} of ${health.sweOpenTotal.toLocaleString()} OPEN SWE rows evaluated · ${health.sweSubcategoryLabelled.toLocaleString()} labelled · reveal at ${REVEAL_THRESHOLD_PCT}%`
                    : 'No OPEN software-engineering rows yet'
                }
              />
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                Coverage counts EVALUATED rows, not labelled ones — an empty
                array is a legitimate terminal answer ("we looked, no specialty
                applies"), so counting only non-empty results would asymptote
                below the threshold and never cross it.
              </Typography>
              {health.subcategoryUnknownSlugs > 0 && (
                <Alert severity="warning" sx={{ mt: 1 }}>
                  {health.subcategoryUnknownSlugs.toLocaleString()} persisted
                  subcategory slug(s) are not in the taxonomy. This must be
                  permanently 0 — the array has no foreign key, and this counter
                  is the only thing that catches a producer writing slugs the
                  taxonomy does not contain.
                </Alert>
              )}
            </Grid>
            <Grid size={{ xs: 12, sm: 6 }}>
              <FormControlLabel
                control={
                  <Switch
                    checked={revealEnabled}
                    disabled={savingSetting || settingsQuery.isLoading}
                    onChange={(e) => void handleRevealToggle(e.target.checked)}
                  />
                }
                label="Show the subcategory filter to users"
              />
              <Typography variant="caption" color="text.secondary" display="block">
                Users' browsers pick the change up within about a minute.
                {/* ⚠ This sentence is the flag query's TTL restated in prose.
                    If that TTL moves, this line moves with it. */}
              </Typography>
              {settingError && (
                <Alert severity="error" onClose={() => setSettingError(null)} sx={{ mt: 1 }}>
                  {settingError}
                </Alert>
              )}
            </Grid>
          </Grid>
        </Paper>
      )}

      {/* 3. Tick EKG + charts (the push-metrics surface). */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2" gutterBottom>
          Ticks
        </Typography>
        {ticksQuery.error ? (
          <ErrorState
            inline
            message={extractErrorMessage(ticksQuery.error, 'Failed to load ticks')}
            onRetry={() => ticksQuery.refetch()}
          />
        ) : ticksSlotLoading || !ticks ? (
          <LoadingState minHeight={120} caption="Loading ticks…" />
        ) : (
          <>
            <TickStrip ticks={ticks.ticks} windowHours={ticks.windowHours} />
            <Box sx={{ mt: 3 }}>
              <TickCharts ticks={ticks.ticks} />
            </Box>
          </>
        )}
      </Paper>

      {/* 4. Quality: latest eval scorecard + runtime knobs. */}
      {ticks?.latestScorecard && (
        <Paper
          variant="outlined"
          sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
        >
          <Typography variant="h6" component="h2" gutterBottom>
            Quality — latest eval scorecard
          </Typography>
          <ScorecardPanel
            scorecard={ticks.latestScorecard}
            scorecardTickUuid={ticks.latestScorecardTickUuid}
            knobs={ticks.latestKnobs}
          />
        </Paper>
      )}

      {/* 5. Needs-human triage queue (self-contained). */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2" gutterBottom>
          Needs human
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Rows the judge flagged for a person. Corrections publish immediately, lock the row
          against automated overwrite, and feed the enricher's golden set as human labels.
        </Typography>
        <NeedsHumanTable />
      </Paper>

      {/* 6. Recent writes (self-contained glance surface). */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <Typography variant="h6" component="h2" gutterBottom>
          Recent enrichments
        </Typography>
        <RecentEnrichmentsTable />
      </Paper>
    </Container>
  );
}
