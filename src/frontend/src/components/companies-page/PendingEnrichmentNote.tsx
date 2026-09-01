import Alert from '@mui/material/Alert';
import { useAppSelector } from '../../app/hooks';
import { selectPendingEnrichmentHidden } from '../../features/filters/selectors/graphFiltersSelectors';

/**
 * The one line that explains an empty chart on a board you just added.
 *
 * A category or level filter hides any job we have not enriched yet — which is
 * correct, and is not changed here — but on a brand-new custom board that is
 * very nearly every job, so the page goes blank and says nothing. Enrichment is
 * a background pass that catches up on its own, so the honest thing to say is
 * that these jobs exist, that they are on their way, and which filter is
 * currently hiding them.
 *
 * Renders nothing at all unless a filter is genuinely hiding unenriched jobs on
 * a custom board (`selectPendingEnrichmentHidden` returns a frozen zero by
 * identity otherwise), so it costs public companies nothing and is invisible
 * with the custom-companies flag off.
 */
export function PendingEnrichmentNote() {
  const { hidden, total, blockedBy } = useAppSelector(selectPendingEnrichmentHidden);

  if (hidden === 0) return null;

  // Name only the filter(s) actually in force. "Clear the category and level
  // filters" when only the category one is set sends the reader looking for a
  // control they never touched.
  const both = blockedBy === 'both';
  const filterPhrase = both ? 'category and level filters are' : `${blockedBy} filter is`;

  return (
    <Alert severity="info" variant="outlined" sx={{ mb: 2 }} data-testid="pending-enrichment-note">
      {hidden.toLocaleString()} of {total.toLocaleString()} {total === 1 ? 'job is' : 'jobs are'}{' '}
      still being categorized, so the {filterPhrase} hiding {hidden === 1 ? 'it' : 'them'} for now.
      Clear {both ? 'them' : 'it'} to see the whole board — categories fill in on their own as
      enrichment catches up.
    </Alert>
  );
}
