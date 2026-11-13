import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import {
  CardGridSkeleton,
  SkeletonRegion,
  SKELETON_CONTROL_HEIGHT,
} from '../../components/shared/Skeletons';
import { RESPONSIVE } from '../../config/responsive';

const HERO_COPY_MAX_WIDTH = 780;

export function LandingSkeleton() {
  return (
    <SkeletonRegion label="Loading…">
      <Container
        maxWidth="lg"
        sx={{
          height: RESPONSIVE.landingProto.headerHeight,
          display: 'flex',
          alignItems: 'center',
          gap: RESPONSIVE.landingProto.headerGap,
        }}
      >
        <Typography
          component="div"
          sx={{ fontSize: RESPONSIVE.landingProto.headerWordmarkFontSize, width: 160 }}
        >
          <Skeleton />
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Skeleton variant="rounded" width={88} height={SKELETON_CONTROL_HEIGHT} />
      </Container>

      <Container maxWidth="lg" sx={{ py: RESPONSIVE.landingProto.heroPaddingY }}>
        <Box sx={{ maxWidth: HERO_COPY_MAX_WIDTH, mx: 'auto', textAlign: 'center' }}>
          <Typography
            component="div"
            sx={{ fontSize: RESPONSIVE.landingProto.heroHeadlineFontSize, lineHeight: 1.1 }}
          >
            <Skeleton width="90%" sx={{ mx: 'auto' }} />
            <Skeleton width="60%" sx={{ mx: 'auto' }} />
          </Typography>
          <Typography
            component="div"
            sx={{ fontSize: RESPONSIVE.landingProto.heroSubFontSize, lineHeight: 1.5, mt: 2 }}
          >
            <Skeleton width="80%" sx={{ mx: 'auto' }} />
          </Typography>
        </Box>
        <Box sx={{ mt: 4, display: 'flex', gap: 1.5, justifyContent: 'center', flexWrap: 'wrap' }}>
          <Skeleton variant="rounded" width={160} height={SKELETON_CONTROL_HEIGHT} />
          <Skeleton variant="rounded" width={160} height={SKELETON_CONTROL_HEIGHT} />
        </Box>
        <Box sx={{ mt: 6, height: RESPONSIVE.landingProto.heroSceneHeight }} />
      </Container>

      <Container maxWidth="lg" sx={{ py: RESPONSIVE.landingProto.sectionPaddingY }}>
        <Typography
          component="div"
          sx={{
            fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
            mb: RESPONSIVE.landingProto.sectionTitleMarginBottom,
          }}
        >
          <Skeleton width="40%" />
        </Typography>
        <CardGridSkeleton count={3} itemSize={{ xs: 12, md: 4 }} spacing={3} lines={3} action />
      </Container>
    </SkeletonRegion>
  );
}
