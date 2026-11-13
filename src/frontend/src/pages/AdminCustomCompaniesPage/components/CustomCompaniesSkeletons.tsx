import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import {
  ControlsRowSkeleton,
  SectionSkeleton,
  StatTilesSkeleton,
  TableSkeleton,
  TextSkeleton,
} from '../../../components/shared/Skeletons';
import { RESPONSIVE } from '../../../config/responsive';

const LIVE_SCRAPER_COLUMNS = [
  'Company',
  'Owner',
  'Health',
  'Transport',
  'Last harvest',
  'Jobs',
  'Live?',
] as const;
const ATTEMPT_COLUMNS = [
  '',
  'When',
  'User',
  'Board URL',
  'Resolved as',
  'Outcome',
  'Result',
] as const;
const USER_ROLLUP_COLUMNS = [
  'User',
  'Attempts',
  'Added',
  'Refused',
  'Stuck',
  'Linked',
  'Owns now',
  'First → last',
] as const;

export function HeadlineCountsSkeleton() {
  return <StatTilesSkeleton count={4} size={{ xs: 6, sm: 3 }} />;
}

export function LiveScrapersTableSkeleton() {
  return (
    <TableSkeleton columns={LIVE_SCRAPER_COLUMNS} surface="none" pagination mobileVariant="list" />
  );
}

export function AddAttemptsTableSkeleton() {
  return <TableSkeleton columns={ATTEMPT_COLUMNS} surface="none" pagination mobileVariant="list" />;
}

export function UsersRollupTableSkeleton() {
  return (
    <TableSkeleton columns={USER_ROLLUP_COLUMNS} surface="none" pagination mobileVariant="list" />
  );
}

function TableSectionSkeleton({
  title,
  filters,
  table,
}: {
  title: string;
  filters: number;
  table: ReactNode;
}) {
  return (
    <SectionSkeleton title={title}>
      <TextSkeleton lines={1} sx={{ mb: 2 }} />
      {filters > 0 && <ControlsRowSkeleton count={filters} width={{ xs: '100%', sm: 200 }} />}
      {table}
      <Box sx={{ mt: 1 }}>
        <TextSkeleton variant="caption" lines={2} />
      </Box>
    </SectionSkeleton>
  );
}

export function CustomCompaniesBodySkeleton() {
  return (
    <>
      <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
        <HeadlineCountsSkeleton />
      </Box>
      <TableSectionSkeleton
        title="Live scrapers"
        filters={2}
        table={<LiveScrapersTableSkeleton />}
      />
      <TableSectionSkeleton title="Add attempts" filters={3} table={<AddAttemptsTableSkeleton />} />
      <TableSectionSkeleton title="Users" filters={0} table={<UsersRollupTableSkeleton />} />
    </>
  );
}
