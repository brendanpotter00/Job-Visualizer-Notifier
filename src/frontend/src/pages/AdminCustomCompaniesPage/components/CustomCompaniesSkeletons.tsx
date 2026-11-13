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

/*
 * Placeholders for the custom-companies admin page, one per slot, built from
 * the shared skeleton pieces. All purely visual: the page wraps each in a
 * single `SkeletonRegion` naming what is loading.
 *
 * Each of the three tables swaps to a tappable list on phones, so their
 * placeholders do too (`mobileVariant="list"`).
 */

/** `LiveScrapersTable`'s header. */
const LIVE_SCRAPER_COLUMNS = ['Company', 'Owner', 'Health', 'Transport', 'Last harvest', 'Jobs', 'Live?'] as const;
/** `AddAttemptsTable`'s header (the first, unlabelled column holds the expand toggle). */
const ATTEMPT_COLUMNS = ['', 'When', 'User', 'Board URL', 'Resolved as', 'Outcome', 'Result'] as const;
/** `UsersRollupTable`'s header. */
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

/** The four headline stat tiles. */
export function HeadlineCountsSkeleton() {
  return <StatTilesSkeleton count={4} size={{ xs: 6, sm: 3 }} />;
}

/** The live-scrapers table. */
export function LiveScrapersTableSkeleton() {
  return (
    <TableSkeleton columns={LIVE_SCRAPER_COLUMNS} surface="none" pagination mobileVariant="list" />
  );
}

/** The add-attempts table. */
export function AddAttemptsTableSkeleton() {
  return <TableSkeleton columns={ATTEMPT_COLUMNS} surface="none" pagination mobileVariant="list" />;
}

/** The per-user rollup table. */
export function UsersRollupTableSkeleton() {
  return (
    <TableSkeleton columns={USER_ROLLUP_COLUMNS} surface="none" pagination mobileVariant="list" />
  );
}

/** One table section: title, description line, filter row, table, footnote. */
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
      {filters > 0 && (
        <ControlsRowSkeleton count={filters} width={{ xs: '100%', sm: 200 }} />
      )}
      {table}
      <Box sx={{ mt: 1 }}>
        <TextSkeleton variant="caption" lines={2} />
      </Box>
    </SectionSkeleton>
  );
}

/**
 * The page below the header, for the first load when neither read has landed:
 * the headline tiles and the three table sections, in page order.
 */
export function CustomCompaniesBodySkeleton() {
  return (
    <>
      <Box sx={{ mb: RESPONSIVE.spacing.sectionMarginB }}>
        <HeadlineCountsSkeleton />
      </Box>
      <TableSectionSkeleton title="Live scrapers" filters={2} table={<LiveScrapersTableSkeleton />} />
      <TableSectionSkeleton title="Add attempts" filters={3} table={<AddAttemptsTableSkeleton />} />
      <TableSectionSkeleton title="Users" filters={0} table={<UsersRollupTableSkeleton />} />
    </>
  );
}
