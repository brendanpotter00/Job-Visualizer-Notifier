import { Divider, Paper, Stack } from '@mui/material';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { MetricsDashboard } from '../../components/companies-page/MetricsDashboard/MetricsDashboard';
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
 * Displays either a loading indicator or the main content. The metrics
 * dashboard sits on top; below it, the graph and the job list share a single
 * `<Paper>` card (separated by a divider) because they are driven by one shared
 * set of filters — the list reflects the graph.
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
      <MetricsDashboard />

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <GraphSection />
        <Divider sx={{ my: 3 }} />
        <ListSection />
      </Paper>
    </Stack>
  );
}
