import { Box, Grid, Skeleton, Typography } from '@mui/material';
import { SkeletonRegion } from '../../../components/shared/Skeletons';
import { JobCardSkeleton } from '../../../components/shared/LoadingIndicator';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';
import { FRESH_JOBS_HEADING_ID } from './FreshJobsTriptych';
import { SectionIntro } from './SectionIntro';
import { TRIPTYCH_SLOT_IDS } from './triptychJobs';

export function FreshJobsTriptychSkeleton({ content }: { content: LandingContent['freshJobs'] }) {
  return (
    <Box data-testid="fresh-jobs-skeleton">
      <SkeletonRegion label={content.loadingLabel}>
        <SectionIntro heading={content.heading} headingId={FRESH_JOBS_HEADING_ID} as="p" />
        <Grid container spacing={{ xs: 2, sm: 3 }}>
          {TRIPTYCH_SLOT_IDS.map((id) => (
            <Grid key={id} size={{ xs: 12, sm: 4 }} data-testid="fresh-jobs-skeleton-slot">
              <Typography variant="overline" component="div" sx={{ display: 'block', mb: 1 }}>
                <Skeleton width="45%" />
              </Typography>
              <Box
                sx={{
                  display: 'grid',
                  minHeight: RESPONSIVE.landingProto.freshJobsSkeletonMinHeight,
                  '& > .MuiCard-root': { height: '100%' },
                }}
              >
                <JobCardSkeleton />
              </Box>
            </Grid>
          ))}
        </Grid>
      </SkeletonRegion>
    </Box>
  );
}
