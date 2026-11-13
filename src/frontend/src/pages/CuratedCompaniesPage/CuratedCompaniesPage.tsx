import { Box, Container, Skeleton, Typography } from '@mui/material';
import { useListCuratedCompaniesQuery } from '../../features/companies/companiesApi';
import { CardGridSkeleton, SkeletonRegion } from '../../components/shared/Skeletons';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { CuratedCompaniesGrid } from './CuratedCompaniesGrid';
import { RESPONSIVE } from '../../config/responsive';

const SKELETON_CARD_COUNT = 6;

const SEARCH_FIELD_HEIGHT = 56;

function CuratedCompaniesSkeleton() {
  return (
    <SkeletonRegion label="Loading companies…">
      <Box sx={{ mb: 3 }}>
        <Skeleton variant="rounded" height={SEARCH_FIELD_HEIGHT} />
      </Box>
      <CardGridSkeleton
        count={SKELETON_CARD_COUNT}
        itemSize={RESPONSIVE.curatedCard.gridItemSize}
        spacing={RESPONSIVE.curatedCard.gridSpacing}
        mediaHeight={{
          xs: RESPONSIVE.curatedCard.wordmarkHeight.compact,
          sm: RESPONSIVE.curatedCard.wordmarkHeight.default,
        }}
        contentPadding={RESPONSIVE.curatedCard.contentPadding}
        lines={3}
        action
      />
    </SkeletonRegion>
  );
}

/**
 * Public directory of every company this site tracks. Data is sourced from the
 * backend `companies` table (via `/api/companies`), so a company added to the
 * DB appears here automatically and is discoverable by other agents.
 */
export function CuratedCompaniesPage() {
  const { data, isLoading, isError, error, refetch } = useListCuratedCompaniesQuery();

  return (
    <Container maxWidth="xl" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
        <Typography variant="h4" component="h1">
          Curated Companies
        </Typography>
      </Box>

      {isLoading && <CuratedCompaniesSkeleton />}

      {isError && (
        <ErrorState
          inline
          message={extractErrorMessage(error, 'Failed to load companies.')}
          onRetry={refetch}
        />
      )}

      {!isLoading && !isError && data && <CuratedCompaniesGrid companies={data} />}
    </Container>
  );
}
