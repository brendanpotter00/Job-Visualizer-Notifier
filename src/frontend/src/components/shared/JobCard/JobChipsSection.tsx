import { Chip, Stack } from '@mui/material';
import { FACET_LABELS } from '../../../constants/enrichment';

/** Max enrichment tag chips shown before collapsing into a "+N" chip. */
const MAX_VISIBLE_ENRICHMENT_TAGS = 4;

interface JobChipsSectionProps {
  /**
   * Department name to display
   */
  department?: string;
  /**
   * Whether the job is remote
   */
  isRemote?: boolean;
  /** Enrichment category slug (rendered with its display label). */
  category?: string | null;
  /** Enrichment level slug (rendered with its display label). */
  level?: string | null;
  /** Free-form enrichment skill tags (lowercase slugs). */
  enrichmentTags?: string[];
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
 * - Department chip (if present)
 * - Remote chip (if job is remote)
 * - Enrichment category/level chips (filled, quiet) when the job is enriched
 * - Enrichment skill-tag chips, capped at MAX_VISIBLE_ENRICHMENT_TAGS with a
 *   "+N" overflow chip (job lists render hundreds of cards — unbounded chip
 *   rows would dominate the card)
 */
export function JobChipsSection({
  department,
  isRemote,
  category,
  level,
  enrichmentTags,
}: JobChipsSectionProps) {
  const tags = enrichmentTags ?? [];
  const visibleTags = tags.slice(0, MAX_VISIBLE_ENRICHMENT_TAGS);
  const overflow = tags.length - visibleTags.length;
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {department && <Chip label={department} size="small" variant="outlined" />}
      {isRemote && <Chip label="Remote" size="small" color="primary" variant="outlined" />}
      {category && <Chip label={facetLabel(category)} size="small" variant="filled" />}
      {level && <Chip label={facetLabel(level)} size="small" variant="filled" />}
      {visibleTags.map((tag) => (
        <Chip key={tag} label={tag} size="small" variant="outlined" sx={{ opacity: 0.75 }} />
      ))}
      {overflow > 0 && (
        <Chip label={`+${overflow}`} size="small" variant="outlined" sx={{ opacity: 0.6 }} />
      )}
    </Stack>
  );
}
