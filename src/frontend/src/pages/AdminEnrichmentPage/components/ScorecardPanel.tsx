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
  // ⚠ PRE-EXISTING BUG, FIXED HERE. This panel read `judge_kappa`, but the
  // enricher's `scoring.py::to_dict` emits `judge_kappa_prejudge`. That tile has
  // therefore ALWAYS rendered '—' against real payloads — masked the whole time
  // by a test fixture that supplied the key the code was looking for rather than
  // the key the producer actually sends. Read the real key first, keep the old
  // one as a fallback for any archived scorecard.
  const judgeKappa =
    metric(scorecard, 'judge_kappa_prejudge') ?? metric(scorecard, 'judge_kappa');

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
      value: judgeKappa === null ? '—' : judgeKappa.toFixed(2),
      meta: 'agreement vs gold — low κ means judge value is unproven, not negative',
    },
  ];

  // CONDITIONAL FIFTH TILE. Pushed only once the enricher's scorer actually
  // emits a subcategory metric, so the panel does not carry a tile stuck at '—'
  // for the weeks between this UI shipping and PR-D landing the metrics.
  //
  // `metric()` already returns null for a missing key, so a key MISMATCH here
  // degrades to "the tile is absent" rather than crashing — which is what makes
  // it safe to parameterize in advance, and also why it needs a deliberate
  // eyeball once the enricher side lands.
  const subcategoryPrimary = metric(scorecard, 'subcategory_primary_accuracy_nonempty');
  if (subcategoryPrimary !== null) {
    tiles.push({
      label: 'Subcategory (primary)',
      value: pct(subcategoryPrimary),
      meta: `set F1 ${pct(metric(scorecard, 'subcategory_set_f1'))} · leak ${pct(
        metric(scorecard, 'subcategory_leak_rate')
      )} · n=${metric(scorecard, 'subcategory_n') ?? '—'}`,
    });
  }

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
