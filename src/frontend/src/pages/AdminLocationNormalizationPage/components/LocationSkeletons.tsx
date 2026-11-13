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

const INTEGRITY_COLUMNS = ['ID', 'Invariant', 'Count', 'Status'] as const;
const ALIAS_FORWARD_COLUMNS = ['Raw text', 'Source', 'Confidence', 'Canonical', 'Actions'] as const;
const ALIAS_REVERSE_COLUMNS = ['Canonical', 'Kind', 'Raw texts'] as const;
const PROBLEM_JOB_COLUMNS = ['ID', 'Title', 'Company', 'Location', 'Status', 'Action'] as const;

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

export function AliasForwardTableSkeleton() {
  return <TableSkeleton columns={ALIAS_FORWARD_COLUMNS} surface="none" pagination />;
}

export function AliasReverseTableSkeleton() {
  return <TableSkeleton columns={ALIAS_REVERSE_COLUMNS} surface="none" />;
}

export function ProblemJobsTableSkeleton() {
  return <TableSkeleton columns={PROBLEM_JOB_COLUMNS} surface="none" pagination />;
}

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
