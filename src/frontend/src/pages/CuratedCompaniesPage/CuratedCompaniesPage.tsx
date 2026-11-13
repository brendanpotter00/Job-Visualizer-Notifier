import { Box, Container, Skeleton, Typography } from '@mui/material';
import { useListCuratedCompaniesQuery } from '../../features/companies/companiesApi';
import { CardGridSkeleton, SkeletonRegion } from '../../components/shared/Skeletons';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { CuratedCompaniesGrid } from './CuratedCompaniesGrid';
import { RESPONSIVE } from '../../config/responsive';

/** Cards in the first-load grid: two full rows of the 3-up desktop layout. */
const SKELETON_CARD_COUNT = 6;

/** The search field above the grid is MUI's default (medium) outlined input. */
const SEARCH_FIELD_HEIGHT = 56;

/**
 * First-load placeholder for the directory, shaped like `CuratedCompaniesGrid`:
 * the full-width search field, then the responsive card grid (1-up phone,
 * 2-up tablet, 3-up desktop) with a wordmark block, blurb lines and the
 * "See company hiring trends" link line in each card.
 */
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
