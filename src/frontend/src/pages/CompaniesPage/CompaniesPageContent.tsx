import { Stack } from '@mui/material';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { GraphSection } from '../../components/companies-page/JobPostingsChart/GraphSection';
import { ListSection } from '../../components/companies-page/JobList/ListSection';

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
  if (isLoading) {
    return <LoadingState size={60} minHeight={400} />;
  }

  return (
    <Stack spacing={3}>
      <GraphSection />
      <ListSection />
    </Stack>
  );
}
