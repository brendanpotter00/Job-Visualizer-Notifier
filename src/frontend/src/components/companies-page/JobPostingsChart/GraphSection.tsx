import { useState } from 'react';
import { Box, ButtonBase, Collapse } from '@mui/material';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { JobPostingsChart } from './JobPostingsChart';
import { GraphFilters } from '../GraphFilters.tsx';
import { selectGraphBucketData } from '../../../features/filters/selectors/graphFiltersSelectors.ts';
import {
  selectCurrentCompanyLoadingRtk,
  selectCurrentCompanyError,
} from '../../../features/jobs/jobsSelectors';
import { openGraphModal } from '../../../features/ui/uiSlice';
import { ErrorDisplay } from '../../shared/ErrorDisplay.tsx';
import type { TimeBucket } from '../../../types';
import { RESPONSIVE } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';

const CHART_REGION_ID = 'job-postings-chart-region';

/**
 * Graph section: the shared filter controls and the postings chart.
 *
 * Rendered inside the page's shared `<Paper>` card (alongside the job list), so
 * it no longer supplies its own card wrapper.
 *
 * The timeline chart is collapsible: clicking the header (labelled "Hide graph"
 * / "Show graph") hides only the chart. The filters stay visible because they are
 * the single source of truth that also drives the job list below. State is local
 * and resets to expanded on each visit — there is no persisted preference.
 * Collapsing uses `unmountOnExit` so the (heavy) Recharts canvas is fully torn
 * down while hidden.
 *
 * The header follows the WAI-ARIA disclosure pattern — a `<button>` (carrying
 * `aria-expanded` / `aria-controls`) wrapped in an `<h2>` so the section keeps
 * its heading semantics in the document outline.
 */
export function GraphSection() {
  const dispatch = useAppDispatch();
  const bucketData = useAppSelector(selectGraphBucketData);
  const isLoading = useAppSelector(selectCurrentCompanyLoadingRtk);
  const error = useAppSelector(selectCurrentCompanyError);
  const graphFilters = useAppSelector((state) => state.graphFilters.filters);

  const [collapsed, setCollapsed] = useState(false);
  const isMobile = useIsMobile();

  const handlePointClick = (bucket: TimeBucket) => {
    if (bucket.count > 0) {
      dispatch(
        openGraphModal({
          bucketStart: bucket.bucketStart,
          bucketEnd: bucket.bucketEnd,
          filteredJobIds: bucket.jobIds,
        })
      );
    }
  };

  return (
    <>
      <Box component="h2" sx={{ m: 0, mb: 1 }}>
        <ButtonBase
          onClick={() => setCollapsed((prev) => !prev)}
          aria-expanded={!collapsed}
          aria-controls={CHART_REGION_ID}
          focusRipple
          sx={{
            color: 'text.primary',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 2,
            textAlign: 'left',
            // Bleed the hit area into the card padding so the whole header row
            // is clickable, while the text stays aligned with the content below.
            width: 'calc(100% + 16px)',
            mx: -1,
            px: 1,
            py: 0.75,
            borderRadius: 1,
            transition: (theme) =>
              theme.transitions.create('background-color', {
                duration: theme.transitions.duration.shortest,
              }),
            '&:hover': { bgcolor: 'action.hover' },
            '&.Mui-focusVisible': {
              outline: (theme) => `2px solid ${theme.palette.primary.main}`,
              outlineOffset: 2,
            },
          }}
        >
          <Box component="span" sx={{ typography: 'h5' }}>
            Job Posting Timeline
          </Box>
          <Box
            component="span"
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              flexShrink: 0,
              typography: 'body2',
              fontWeight: 600,
              color: 'text.secondary',
            }}
          >
            {collapsed ? 'Show graph' : 'Hide graph'}
            <KeyboardArrowUpIcon
              fontSize="small"
              sx={{
                color: 'inherit',
                transition: (theme) =>
                  theme.transitions.create('transform', {
                    duration: theme.transitions.duration.shorter,
                  }),
                transform: collapsed ? 'rotate(180deg)' : 'rotate(0deg)',
              }}
            />
          </Box>
        </ButtonBase>
      </Box>

      <GraphFilters />

      <Collapse in={!collapsed} timeout="auto" unmountOnExit>
        <Box id={CHART_REGION_ID}>
          {error ? (
            <ErrorDisplay title="Failed to Load Chart Data" message={error} />
          ) : (
            <JobPostingsChart
              data={bucketData}
              onPointClick={handlePointClick}
              timeWindow={graphFilters.timeWindow}
              isLoading={isLoading}
              height={isMobile ? RESPONSIVE.chart.height.compact : RESPONSIVE.chart.height.default}
            />
          )}
        </Box>
      </Collapse>
    </>
  );
}
