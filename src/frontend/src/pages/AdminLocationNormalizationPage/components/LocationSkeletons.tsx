import Box from '@mui/material/Box';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import {
  ChipRowSkeleton,
  ControlsRowSkeleton,
  SectionSkeleton,
  StatTilesSkeleton,
  StatusBannerSkeleton,
  TableSkeleton,
  TextSkeleton,
} from '../../../components/shared/Skeletons';

/*
 * Placeholders for the location-normalization admin page, one per slot, built
 * from the shared skeleton pieces. All purely visual: the page (or the
 * self-contained table) wraps each in a single `SkeletonRegion`.
 */

/** `IntegrityTable`'s header. */
const INTEGRITY_COLUMNS = ['ID', 'Invariant', 'Count', 'Status'] as const;
/** `AliasBrowser` forward ("Alias → canonical") table header. */
const ALIAS_FORWARD_COLUMNS = ['Raw text', 'Source', 'Confidence', 'Canonical', 'Actions'] as const;
/** `AliasBrowser` reverse ("Canonical → aliases") table header. */
const ALIAS_REVERSE_COLUMNS = ['Canonical', 'Kind', 'Raw texts'] as const;
/** `ProblemJobsTable`'s header. */
const PROBLEM_JOB_COLUMNS = ['ID', 'Title', 'Company', 'Location', 'Status', 'Action'] as const;

/** `HealthOverview`: four stat tiles, the status chip row, the worker-queue chips. */
export function HealthOverviewSkeleton() {
  return (
    <Box>
      <StatTilesSkeleton count={4} size={{ xs: 6, sm: 3 }} sx={{ mb: 2 }} />
      <Box sx={{ mb: 2 }}>
        <ChipRowSkeleton count={3} />
      </Box>
      <Typography variant="overline" component="div">
        <Skeleton width={96} />
      </Typography>
      <Box sx={{ mt: 0.5 }}>
        <ChipRowSkeleton count={4} />
      </Box>
    </Box>
  );
}

/** `IntegrityTable`: the issue-count line over the invariants table. */
export function IntegrityTableSkeleton() {
  return (
    <Box>
      <Typography variant="subtitle2" component="div" sx={{ mb: 1.5 }}>
        <Skeleton width={160} />
      </Typography>
      <TableSkeleton columns={INTEGRITY_COLUMNS} surface="none" rows={6} />
    </Box>
  );
}

/** `AliasBrowser`'s forward table, with its pagination footer. */
export function AliasForwardTableSkeleton() {
  return <TableSkeleton columns={ALIAS_FORWARD_COLUMNS} surface="none" pagination />;
}

/** `AliasBrowser`'s reverse table. */
export function AliasReverseTableSkeleton() {
  return <TableSkeleton columns={ALIAS_REVERSE_COLUMNS} surface="none" />;
}

/** `ProblemJobsTable`, with its pagination footer. */
export function ProblemJobsTableSkeleton() {
  return <TableSkeleton columns={PROBLEM_JOB_COLUMNS} surface="none" pagination />;
}

/** The expanded originals under one alias row: a subtitle and a few string lines. */
export function AliasOriginalsSkeleton() {
  return (
    <Box sx={{ py: 2, pl: 2 }}>
      <Typography variant="subtitle2" component="div" gutterBottom>
        <Skeleton width="40%" />
      </Typography>
      <TextSkeleton lines={3} lastLineWidth="45%" />
    </Box>
  );
}

/**
 * The page below the header, for the first load when neither the health nor
 * the integrity read has landed: every section's placeholder in page order,
 * including the alias browser's tab/search row and the problem-jobs table.
 */
export function LocationPageBodySkeleton() {
  return (
    <>
      <StatusBannerSkeleton />
      <SectionSkeleton title="Health overview">
        <HealthOverviewSkeleton />
      </SectionSkeleton>
      <SectionSkeleton title="Integrity invariants">
        <IntegrityTableSkeleton />
      </SectionSkeleton>
      <SectionSkeleton title="Alias cache browser">
        <ControlsRowSkeleton count={2} width={{ xs: '100%', sm: 280 }} />
        <AliasForwardTableSkeleton />
      </SectionSkeleton>
      <SectionSkeleton title="Problem jobs">
        <ProblemJobsTableSkeleton />
      </SectionSkeleton>
    </>
  );
}
