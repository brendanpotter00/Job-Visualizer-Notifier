import { Box, Container, Typography } from '@mui/material';
import { useListCuratedCompaniesQuery } from '../../features/companies/companiesApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { CuratedCompaniesGrid } from './CuratedCompaniesGrid';
import { RESPONSIVE } from '../../config/responsive';

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
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: 720 }}>
          Every company this site tracks, hand-picked into one place. Search to see what each company
          does and one thing it’s known for — then jump into its hiring trends.
        </Typography>
      </Box>

      {isLoading && <LoadingState size={60} minHeight={400} caption="Loading companies…" />}

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
