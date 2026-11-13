import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import { ChartSkeleton } from '../../../components/shared/LoadingIndicator';
import {
  ControlsRowSkeleton,
  SectionSkeleton,
  StatTileSkeleton,
  StatTilesSkeleton,
  StatusBannerSkeleton,
  TableSkeleton,
  TextSkeleton,
} from '../../../components/shared/Skeletons';
import { RESPONSIVE } from '../../../config/responsive';

/*
 * Placeholders for the enrichment oversight page, one per slot, built from the
 * shared skeleton pieces. All purely visual: the page wraps each in a single
 * `SkeletonRegion` naming what is loading.
 */

/** `PipelineFunnel`'s stacked bar is a fixed 28px band. */
const FUNNEL_BAR_HEIGHT = 28;

/**
 * `TickCharts` height: `adminChart.height.compact` on phones, 240px on desktop
 * (the charts' own desktop literal).
 */
const TICK_CHART_HEIGHT = { xs: RESPONSIVE.adminChart.height.compact, sm: 240 } as const;

/** `NeedsHumanTable`'s header (the first, unlabelled column holds the expand toggle). */
const NEEDS_HUMAN_COLUMNS = ['', 'Job', 'Proposed', 'Confidence', 'Sub conf.', 'Enriched', 'Actions'] as const;

/** `RecentEnrichmentsTable`'s header. */
const RECENT_COLUMNS = ['', 'Job', 'Labels', 'Confidence', 'Outcome', 'Enriched', 'Actions'] as const;

/** Company search + four facet selects above the needs-human table. */
const NEEDS_HUMAN_FILTER_COUNT = 5;

/**
 * Everything the health read paints: the verdict banner, the backlog funnel
 * (bar, legend, four stat tiles) and the subcategory-rollout card. All three
 * appear together when health lands, so they hold their space together.
 */
export function HealthSlotSkeleton() {
  return (
    <>
      <StatusBannerSkeleton />
      <SectionSkeleton title="Backlog funnel">
        <Skeleton variant="rounded" height={FUNNEL_BAR_HEIGHT} />
        <Typography variant="caption" component="div" sx={{ mt: 1 }}>
          <Skeleton width="50%" />
        </Typography>
        <StatTilesSkeleton count={4} size={{ xs: 6, sm: 3 }} sx={{ mt: 1.5 }} />
      </SectionSkeleton>
      <SectionSkeleton title="Subcategory rollout">
        <Grid container spacing={2} sx={{ alignItems: 'flex-start' }}>
          <Grid size={{ xs: 12, sm: 6 }}>
            <StatTileSkeleton />
            <TextSkeleton variant="caption" lines={2} sx={{ mt: 1 }} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <Typography variant="body1" component="div">
              <Skeleton width="70%" />
            </Typography>
            <TextSkeleton variant="caption" lines={2} />
          </Grid>
        </Grid>
      </SectionSkeleton>
    </>
  );
}

/** The ticks card body: the EKG strip over the two side-by-side charts. */
export function TicksSlotSkeleton() {
  return (
    <>
      <Skeleton variant="rounded" height={FUNNEL_BAR_HEIGHT} />
      <Box
        sx={{
          mt: 3,
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
          gap: 3,
        }}
      >
        {[0, 1].map((i) => (
          <Box key={i}>
            <Typography variant="subtitle2" component="div" gutterBottom>
              <Skeleton width="40%" />
            </Typography>
            <ChartSkeleton height={TICK_CHART_HEIGHT} />
          </Box>
        ))}
      </Box>
    </>
  );
}

/** The needs-human queue table (header, rows, pagination). */
export function NeedsHumanTableSkeleton() {
  return <TableSkeleton columns={NEEDS_HUMAN_COLUMNS} surface="none" pagination />;
}

/** The recent-enrichments table (no pagination — it is a fixed last-25 glance). */
export function RecentEnrichmentsTableSkeleton() {
  return <TableSkeleton columns={RECENT_COLUMNS} surface="none" />;
}

/**
 * The page below the header, for the first load when nothing has arrived:
 * every slot's placeholder in page order, including the two self-contained
 * tables (whose own requests only start once the page renders them).
 */
export function EnrichmentPageBodySkeleton() {
  return (
    <>
      <HealthSlotSkeleton />
      <SectionSkeleton title="Ticks">
        <TicksSlotSkeleton />
      </SectionSkeleton>
      <SectionSkeleton title="Needs human">
        <TextSkeleton lines={1} sx={{ mb: 2 }} />
        <ControlsRowSkeleton
          count={NEEDS_HUMAN_FILTER_COUNT}
          width={{ xs: '100%', sm: 180 }}
        />
        <NeedsHumanTableSkeleton />
      </SectionSkeleton>
      <SectionSkeleton title="Recent enrichments">
        <RecentEnrichmentsTableSkeleton />
      </SectionSkeleton>
    </>
  );
}
