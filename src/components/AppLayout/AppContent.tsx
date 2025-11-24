import { Box, CircularProgress, Stack } from '@mui/material';
import { GraphSection } from '../JobPostingsChart/GraphSection';
import { ListSection } from '../JobList/ListSection';

/**
 * Props for the AppContent component
 */
interface AppContentProps {
  /** Whether data is currently being loaded */
  isLoading: boolean;
}

/**
 * Main application content component
 *
 * Displays either a loading indicator or the main content sections
 * (graph and list) based on the loading state.
 *
 * @param props - Component props
 * @returns Loading indicator or main content sections
 */
export function AppContent({ isLoading }: AppContentProps) {
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
        <CircularProgress size={60} />
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
