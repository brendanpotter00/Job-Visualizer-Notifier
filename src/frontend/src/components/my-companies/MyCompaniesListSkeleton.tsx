import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { CardListSkeleton } from '../shared/Skeletons';

/** Placeholder rows while the tracked-companies list loads. */
const ROW_COUNT = 3;

/**
 * Placeholder for `MyCompaniesList`: the "Your companies" heading over a short
 * stack of outlined company rows (name, two metadata lines, and the trailing
 * remove control), spaced like the real list.
 *
 * Purely visual — the caller wraps it in a `SkeletonRegion`, so the Add
 * Companies page can reuse it inside its own whole-page placeholder without
 * announcing the wait twice.
 */
export function MyCompaniesListSkeleton() {
  return (
    <Box data-testid="my-companies-list-skeleton">
      <Typography variant="h6" component="div" gutterBottom>
        Your companies
      </Typography>
      <CardListSkeleton count={ROW_COUNT} lines={2} trailing spacing={1.5} />
    </Box>
  );
}
