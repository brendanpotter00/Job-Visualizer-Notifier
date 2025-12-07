import { Box, CircularProgress, Stack, Typography } from '@mui/material';
import { GraphSection } from '../../components/companies-page/JobPostingsChart/GraphSection';
import { ListSection } from '../../components/companies-page/JobList/ListSection';
import { useAppSelector } from '../../app/hooks';
import { ATSConstants } from '../../api/types';

/**
 * Props for the CompaniesPageContent component
 */
interface CompaniesPageContentProps {
  /** Whether data is currently being loaded */
  isLoading: boolean;
}

/**
 * Main companies page content component
 *
 * Displays either a loading indicator or the main content sections
 * (graph and list) based on the loading state.
 *
 * @param props - Component props
 * @returns Loading indicator or main content sections
 */
export function CompaniesPageContent({ isLoading }: CompaniesPageContentProps) {
  const selectedATS = useAppSelector((state) => state.app.selectedATS);
  if (isLoading) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '400px',
        }}
      >
        <Stack direction="column" spacing={2} sx={{ alignItems: 'center', textAlign: 'center' }}>
          <CircularProgress size={60} />
          {selectedATS === ATSConstants.Workday && (
            <Typography variant="body1" color="text.disabled">
              Workday source requires more loading time to fetch all paginated jobs...
            </Typography>
          )}
        </Stack>
      </Box>
    );
  }

  return (
    <Stack spacing={3}>
      <GraphSection />
      <ListSection />
    </Stack>
  );
}
