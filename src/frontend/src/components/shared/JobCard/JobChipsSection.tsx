import { Chip, Stack } from '@mui/material';
import { FACET_LABELS } from '../../../constants/enrichment';

interface JobChipsSectionProps {
  /** Enrichment category slug (rendered with its display label). */
  category?: string | null;
  /** Enrichment level slug (rendered with its display label). */
  level?: string | null;
}

/** Slug -> label with a readable fallback for unknown slugs. */
function facetLabel(slug: string): string {
  return FACET_LABELS[slug] ?? slug.split('_').join(' ');
}

/**
 * Enrichment chips (category + level) for a job card.
 *
 * The Remote chip deliberately does NOT live here: it says *where* the job is,
 * so `JobListingCard` renders it in the location row instead of down here with
 * the "what kind of job is this" facets.
 *
 * Renders nothing when the job has no enrichment, so an unenriched card doesn't
 * leave an empty row eating the parent Stack's spacing.
 */
export function JobChipsSection({ category, level }: JobChipsSectionProps) {
  if (!category && !level) return null;

  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {category && <Chip label={facetLabel(category)} size="small" variant="filled" />}
      {level && <Chip label={facetLabel(level)} size="small" variant="filled" />}
    </Stack>
  );
}
