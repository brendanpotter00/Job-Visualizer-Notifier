import { Box, Divider, Paper, Skeleton, Stack, Typography } from '@mui/material';
import { ChartSkeleton, JobListSkeleton } from '../../components/shared/LoadingIndicator';
import { SkeletonRegion } from '../../components/shared/Skeletons';
import { MetricsDashboard } from '../../components/companies-page/MetricsDashboard/MetricsDashboard';
import { GraphSection } from '../../components/companies-page/JobPostingsChart/GraphSection';
import { ListSection } from '../../components/companies-page/JobList/ListSection';
import { RESPONSIVE } from '../../config/responsive';

/**
 * Props for the CompaniesPageContent component
 */
interface CompaniesPageContentProps {
  /** Whether data is currently being loaded */
  isLoading: boolean;
}

/** The three window labels `MetricsRow` renders, so the skeleton shows them too. */
const METRIC_LABELS = ['Past 3 Days', 'Past 24 Hours', 'Past 12 Hours'] as const;
/** The two link labels `LinksRow` renders. */
const LINK_LABELS = ['Official Job Postings', 'Find Recruiters'] as const;
/** GraphFilters' second row: time window, category, level, location. */
const FILTER_ROW_CONTROLS = [0, 1, 2, 3] as const;

/** Responsive chart height, matching what `GraphSection` hands `JobPostingsChart`. */
const CHART_HEIGHT = {
  xs: RESPONSIVE.chart.height.compact,
  sm: RESPONSIVE.chart.height.default,
} as const;

/**
 * First-load placeholder for the company hiring-trend page, laid out like the
 * loaded content: the metrics card (three window counts over the two links) on
 * top, then the shared graph + list card. Static labels render as real text;
 * only the numbers, filters, chart and job cards are placeholders.
 */
function CompaniesPageContentSkeleton() {
  return (
    <SkeletonRegion label="Loading job data…">
      <Stack spacing={3}>
        <Paper sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}>
          <Stack
            direction="row"
            spacing={RESPONSIVE.spacing.rowSpacing}
            divider={<Divider orientation="vertical" flexItem />}
            sx={{ mb: { xs: 2, sm: 3 } }}
          >
            {METRIC_LABELS.map((label) => (
              <Box key={label} sx={{ flex: 1, textAlign: 'center', minWidth: 0 }}>
                <Typography
                  variant="h3"
                  component="div"
                  gutterBottom
                  sx={{ fontSize: RESPONSIVE.fontSize.metricValue }}
                >
                  <Skeleton width="40%" sx={{ mx: 'auto' }} />
                </Typography>
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ fontSize: RESPONSIVE.fontSize.metricLabel }}
                >
                  {label}
                </Typography>
              </Box>
            ))}
          </Stack>
          <Divider sx={{ mb: 2 }} />
          <Stack direction="row" spacing={{ xs: 2, sm: 3 }}>
            {LINK_LABELS.map((label) => (
              <Box key={label} sx={{ flex: 1 }}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  {label}
                </Typography>
                <Typography variant="body1" component="div">
                  <Skeleton width="50%" />
                </Typography>
              </Box>
            ))}
          </Stack>
        </Paper>

        <Paper sx={{ p: { xs: 2, sm: 3 } }}>
          <Typography variant="h5" component="div" sx={{ mb: 1, py: 0.75 }}>
            Job Posting Timeline
          </Typography>
          <Stack
            spacing={RESPONSIVE.spacing.filterSpacing}
            sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}
          >
            <Skeleton variant="rounded" sx={{ height: RESPONSIVE.control.minHeight }} />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={RESPONSIVE.spacing.filterSpacing}>
              {FILTER_ROW_CONTROLS.map((i) => (
                <Skeleton
                  key={i}
                  variant="rounded"
                  // Row on desktop (equal widths); stacked full-width on phones,
                  // where a zero flex-basis would collapse each one's height.
                  sx={{ flex: { xs: 'none', sm: 1 }, height: RESPONSIVE.control.minHeight }}
                />
              ))}
            </Stack>
          </Stack>
          <ChartSkeleton height={CHART_HEIGHT} />
          <Divider sx={{ my: 3 }} />
          <Typography variant="h5" component="div" gutterBottom>
            Job Listings
          </Typography>
          <JobListSkeleton count={3} />
        </Paper>
      </Stack>
    </SkeletonRegion>
  );
}

/**
 * Main companies page content component
 *
 * Displays either a first-load skeleton or the main content. The metrics
 * dashboard sits on top; below it, the graph and the job list share a single
 * `<Paper>` card (separated by a divider) because they are driven by one shared
 * set of filters — the list reflects the graph.
 *
 * @param props - Component props
 * @returns Loading skeleton or main content sections
 */
export function CompaniesPageContent({ isLoading }: CompaniesPageContentProps) {
  if (isLoading) {
    return <CompaniesPageContentSkeleton />;
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
