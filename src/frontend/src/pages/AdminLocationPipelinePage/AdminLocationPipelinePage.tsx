import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';
import { usePipelinePlayer, type Phase } from './usePipelinePlayer';
import { PlaybackControls } from './components/PlaybackControls';
import { PipelineRail } from './components/PipelineRail';
import { StageDetailPanel } from './components/StageDetailPanel';
import { DataTablesPanel } from './components/DataTablesPanel';

type StatusColor = 'default' | 'success' | 'error' | 'warning';

const PHASE_STATUS: Record<Phase, { label: string; color: StatusColor }> = {
  running: { label: 'status: NULL', color: 'default' },
  done: { label: 'status: done', color: 'success' },
  failed: { label: 'status: failed', color: 'error' },
  deferred: { label: 'status: NULL (deferred)', color: 'warning' },
};

const BRANCH_LEGEND: { key: string; label: string; color: StatusColor | 'info' }[] = [
  { key: 'hit', label: 'Tier-1 HIT → skip LLM', color: 'success' },
  { key: 'miss', label: 'Tier-1 MISS → call Haiku', color: 'info' },
  { key: 'fail', label: 'confidence < 0.5 → failed', color: 'error' },
  { key: 'nokey', label: 'no API key → stays NULL', color: 'warning' },
];

/**
 * Admin explainer page: a scripted, animated walkthrough of the two-tier
 * location-normalization pipeline. Read-only — every value is a fixture.
 */
export function AdminLocationPipelinePage() {
  const player = usePipelinePlayer();
  const { example, phase } = player;
  const status = PHASE_STATUS[phase];
  const currentStage = player.stages[player.currentStageIndex];
  const io = example.io[currentStage.id];
  const isFailedStage = phase === 'failed' && currentStage.id === 'floor';

  return (
    <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          Location Pipeline
        </Typography>
        <Typography variant="body2" color="text.secondary">
          A read-only walkthrough of how a raw job-location string becomes structured, canonical
          locations — stage by stage. Pick an example and press play.
        </Typography>
      </Box>

      {/* 1. Player: controls + animated rail + branch legend. */}
      <Paper
        variant="outlined"
        sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}
      >
        <PlaybackControls
          examples={player.examples}
          exampleIndex={player.exampleIndex}
          onSelect={player.selectExample}
          isPlaying={player.isPlaying}
          onToggle={player.toggle}
          onStepBack={player.stepBack}
          onStepForward={player.stepForward}
          onRestart={player.restart}
          currentStageIndex={player.currentStageIndex}
          totalStages={player.stages.length}
        />

        <Box
          sx={{ mt: 2, mb: 0.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}
        >
          <Typography variant="caption" color="text.secondary">
            Raw input
          </Typography>
          <Chip size="small" label={example.raw} sx={{ fontFamily: 'monospace' }} />
        </Box>

        <PipelineRail
          stages={player.stages}
          path={player.path}
          cursor={player.cursor}
          currentStageIndex={player.currentStageIndex}
          branch={example.branch}
          phase={phase}
        />

        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
          {BRANCH_LEGEND.map((branch) => {
            const active = branch.key === example.branch;
            return (
              <Chip
                key={branch.key}
                size="small"
                label={branch.label}
                variant={active ? 'filled' : 'outlined'}
                color={active ? branch.color : undefined}
              />
            );
          })}
        </Box>
      </Paper>

      {/* 2. Active-stage detail + the four tables. */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
          gap: 3,
          mb: 3,
        }}
      >
        <StageDetailPanel stage={currentStage} io={io} isFailed={isFailedStage} />
        <DataTablesPanel
          rows={example.rows}
          visible={player.showRows}
          statusLabel={status.label}
          statusColor={status.color}
        />
      </Box>

      {/* 3. Outcome note (only once the run reaches a terminal state). */}
      {phase !== 'running' && (
        <Paper
          variant="outlined"
          sx={{
            p: 2.5,
            mb: RESPONSIVE.spacing.sectionMarginB,
            borderLeft: 6,
            borderLeftColor: `${status.color}.main`,
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
            <Chip
              size="small"
              label={phase}
              color={status.color === 'default' ? undefined : status.color}
            />
            <Typography variant="body2">{example.resultNote}</Typography>
          </Box>
        </Paper>
      )}

      {/* 4. How to read this + safety-net context. */}
      <Paper variant="outlined" sx={{ p: RESPONSIVE.spacing.paperPadding }}>
        <Typography variant="h6" component="h2" gutterBottom>
          How to read this
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          The pipeline runs in the backend Procrastinate worker. Tier-1 is a deterministic alias
          cache; Tier-2 is a Claude Haiku 4.5 call made only on a cache miss. A periodic{' '}
          <Box component="code" sx={{ fontFamily: 'monospace' }}>
            scan_unnormalized
          </Box>{' '}
          task (every 5 min) re-queues any job left with{' '}
          <Box component="code" sx={{ fontFamily: 'monospace' }}>
            status IS NULL
          </Box>{' '}
          — the safety net behind the no-key and failure paths.
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Source: Location Normalization (#145) · prod monitor + canonicalization (#149).
        </Typography>
      </Paper>
    </Container>
  );
}
