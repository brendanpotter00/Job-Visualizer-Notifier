import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import { ControlsRowSkeleton, SKELETON_CONTROL_HEIGHT } from '../shared/Skeletons';

export interface SavedFiltersSectionSkeletonProps {
  title: string;
  controls?: number;
}

export function SavedFiltersSectionSkeleton({
  title,
  controls = 2,
}: SavedFiltersSectionSkeletonProps) {
  return (
    <Paper sx={{ borderRadius: 1 }} data-testid="saved-filters-section-skeleton">
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
        <Skeleton variant="rounded" width={140} height={SKELETON_CONTROL_HEIGHT} sx={{ mt: 3 }} />
      </Box>
    </Paper>
  );
}
