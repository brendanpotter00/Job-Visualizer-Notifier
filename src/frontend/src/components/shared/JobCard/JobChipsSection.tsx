import { Chip, Stack } from '@mui/material';
import { FACET_LABELS } from '../../../constants/enrichment';

interface JobChipsSectionProps {
  /**
   * Whether the job is remote
   */
  isRemote?: boolean;
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
 * Shared component for rendering job metadata chips
 * Used by both JobCard and RecentJobCard components
 *
 * Displays:
 * - Remote chip (if job is remote)
 * - Enrichment category/level chips (filled, quiet) when the job is enriched
 */
export function JobChipsSection({ isRemote, category, level }: JobChipsSectionProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {isRemote && <Chip label="Remote" size="small" color="primary" variant="outlined" />}
      {category && <Chip label={facetLabel(category)} size="small" variant="filled" />}
      {level && <Chip label={facetLabel(level)} size="small" variant="filled" />}
    </Stack>
  );
}
