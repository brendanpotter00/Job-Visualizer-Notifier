import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Grid from '@mui/material/Grid';
import Typography from '@mui/material/Typography';
import { StatTile } from '../../AdminUsersPage/components/StatTile';

interface ScorecardPanelProps {
  scorecard: Record<string, unknown>;
  scorecardTickUuid: string | null;
  knobs: Record<string, unknown> | null;
}

/** Pick a numeric metric off the (free-shape) scorecard JSON. */
function metric(scorecard: Record<string, unknown>, key: string): number | null {
  const v = scorecard[key];
  return typeof v === 'number' ? v : null;
}

function pct(v: number | null): string {
  return v === null ? '—' : `${(v * 100).toFixed(1)}%`;
}

/**
 * The latest eval scorecard the enricher pushed, shown with the metric
 * hierarchy the eval work established: level FILTER-CONSISTENT accuracy is the
 * primary level number (what a user's entry/new-grad filter actually
 * experiences), level-exact is secondary; tag scores use the token-level F1
 * (strict set-match under-credits free-form tags); judge κ is quoted with its
 * known caveat instead of dressed up as a win.
 */
export function ScorecardPanel({ scorecard, scorecardTickUuid, knobs }: ScorecardPanelProps) {
  const tiles = [
    {
      label: 'Category accuracy',
      value: pct(metric(scorecard, 'category_accuracy')),
      meta: `macro-F1 ${pct(metric(scorecard, 'category_f1_macro'))}`,
    },
    {
      label: 'Level (filter-consistent)',
      value: pct(
        metric(scorecard, 'level_filter_consistent_accuracy') ??
          metric(scorecard, 'level_filter_consistent')
      ),
      meta: `exact ${pct(metric(scorecard, 'level_exact_accuracy') ?? metric(scorecard, 'level_exact'))} · what the entry⊇new-grad filter experiences`,
    },
    {
      label: 'Tags (token F1)',
      value: pct(metric(scorecard, 'tags_token_f1')),
      meta: `set-match F1 ${pct(metric(scorecard, 'tags_f1'))} under-credits free-form tags`,
    },
    {
      label: 'Judge κ',
      value:
        metric(scorecard, 'judge_kappa') === null
          ? '—'
          : (metric(scorecard, 'judge_kappa') as number).toFixed(2),
      meta: 'agreement vs gold — low κ means judge value is unproven, not negative',
    },
  ];

  const goldQuality = scorecard['gold_quality'];

  return (
    <Box>
      <Grid container spacing={2}>
        {tiles.map((tile) => (
          <Grid key={tile.label} size={{ xs: 6, md: 3 }}>
            <StatTile label={tile.label} value={tile.value} meta={tile.meta} />
          </Grid>
        ))}
      </Grid>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1.5, alignItems: 'center' }}>
        {typeof goldQuality === 'string' && goldQuality !== 'human' && (
          <Chip
            size="small"
            color="warning"
            variant="outlined"
            label={`gold labels: ${goldQuality} — advisory, not a gate`}
          />
        )}
        {scorecardTickUuid && (
          <Typography variant="caption" color="text.secondary">
            from tick {scorecardTickUuid}
          </Typography>
        )}
        {knobs &&
          Object.entries(knobs)
            .filter(([, v]) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean')
            .map(([k, v]) => (
              <Chip key={k} size="small" variant="outlined" label={`${k}: ${String(v)}`} />
            ))}
      </Box>
    </Box>
  );
}
