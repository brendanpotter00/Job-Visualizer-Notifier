import { Chip, Stack, Tooltip } from '@mui/material';
import { FACET_LABELS } from '../../../constants/enrichment';
import { useSubcategoryRevealEnabled } from '../../../features/settings/subcategoryReveal';

interface JobChipsSectionProps {
  /**
   * Whether the job is remote
   */
  isRemote?: boolean;
  /** Enrichment category slug (rendered with its display label). */
  category?: string | null;
  /** Enrichment level slug (rendered with its display label). */
  level?: string | null;
  /**
   * SWE subcategory slugs, ORDERED — index 0 is the primary specialty.
   *
   * TRI-STATE and read with `?.length`: `null` means never evaluated, `[]` means
   * evaluated with no specialty applying, and both render the CATEGORY chip.
   */
  subcategories?: string[] | null;
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
 *
 * THE SUBCATEGORY CHIPS SUBSTITUTE FOR THE CATEGORY CHIP — they do not add to
 * it. "Software Engineering, Backend" on one card says the same thing twice and
 * costs a row of vertical space per card in a virtualized list.
 *
 * The EMPTY case is spelled out rather than left to the substitution, and it
 * matters more than it looks: roughly 9% of SWE rows end at `[]` permanently,
 * and 100% of them do for the whole backfill window. A literal "the subcategory
 * chips replace the category chip" reading would render NO chip at all for those
 * cards. So:
 *
 *   labelled  -> the specialty chips, primary first
 *   `[]`      -> the CATEGORY chip
 *   `null`    -> the CATEGORY chip
 *   flag off  -> the CATEGORY chip (byte-identical to today)
 *
 * The reveal flag is read from context, not from the query hook: this component
 * renders once per card inside a virtualized list, so the hook form would mint
 * one RTK Query subscription per card.
 */
export function JobChipsSection({
  isRemote,
  category,
  level,
  subcategories,
}: JobChipsSectionProps) {
  const revealSubcategories = useSubcategoryRevealEnabled();
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {isRemote && <Chip label="Remote" size="small" color="primary" variant="outlined" />}
      {revealSubcategories && subcategories?.length
        ? subcategories.map((slug) => (
            <Tooltip
              key={slug}
              title={`${facetLabel(category ?? 'software_engineering')} › ${facetLabel(slug)}`}
            >
              <Chip label={facetLabel(slug)} size="small" variant="filled" />
            </Tooltip>
          ))
        : category && <Chip label={facetLabel(category)} size="small" variant="filled" />}
      {level && <Chip label={facetLabel(level)} size="small" variant="filled" />}
    </Stack>
  );
}
