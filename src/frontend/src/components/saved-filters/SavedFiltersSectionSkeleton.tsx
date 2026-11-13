import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import { ControlsRowSkeleton, SKELETON_CONTROL_HEIGHT } from '../shared/Skeletons';

export interface SavedFiltersSectionSkeletonProps {
  /** The section's real title (static copy such as "Default time windows"). */
  title: string;
  /** Control placeholders in the section body (selects, inputs). */
  controls?: number;
}

/**
 * Placeholder for one Saved Filters section. Every section on that page is a
 * default-expanded `Accordion` with a `px: 4, py: 1` summary holding an `h6`
 * title and `px: 4, pb: 4` details holding a description line, the section's
 * controls, and a save button — this mirrors that box so the page does not
 * shift when a section's data arrives.
 *
 * The title renders as real text (it is static). It is a plain `div`, not a
 * heading, so the page's heading outline only ever lists loaded sections.
 * Purely visual: wrap it (or a stack of them) in one `SkeletonRegion`.
 */
export function SavedFiltersSectionSkeleton({ title, controls = 2 }: SavedFiltersSectionSkeletonProps) {
  return (
    <Paper sx={{ borderRadius: 1 }} data-testid="saved-filters-section-skeleton">
      {/* AccordionSummary: 48px min-height row, 12px content margin, px/py from the section. */}
      <Box sx={{ px: 4, py: 1, minHeight: 48, display: 'flex', alignItems: 'center' }}>
        <Typography variant="h6" component="div" sx={{ my: 1.5 }}>
          {title}
        </Typography>
      </Box>
      <Box sx={{ px: 4, pb: 4 }}>
        <Typography variant="body2" component="div" sx={{ mb: 3 }}>
          <Skeleton width="70%" />
        </Typography>
        <ControlsRowSkeleton count={controls} sx={{ mb: 0 }} />
        <Skeleton
          variant="rounded"
          width={140}
          height={SKELETON_CONTROL_HEIGHT}
          sx={{ mt: 3 }}
        />
      </Box>
    </Paper>
  );
}
