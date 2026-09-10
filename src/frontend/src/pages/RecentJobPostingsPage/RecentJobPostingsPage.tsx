import { Container, Typography, Box } from '@mui/material';
import { useRecentJobsSearch } from '../../features/jobs/hooks/useRecentJobsSearch';
import { RecentJobsFilters } from '../../components/recent-jobs-page/RecentJobsFilters';
import { RecentJobsList } from '../../components/recent-jobs-page/RecentJobsList/RecentJobsList';
import { EditCompanyPreferencesRow } from '../../components/recent-jobs-page/EditCompanyPreferencesRow';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { RESPONSIVE } from '../../config/responsive';

/**
 * Recent Job Postings page.
 *
 * Owns the single `useRecentJobsSearch()` call for the page and passes the result
 * down. One call, deliberately: the hook debounces filter edits and freezes the
 * recency bound per walk, and a second instance would keep its own timers and
 * mint a competing cache entry — doubling every request for the same view.
 *
 * The page decides between three mutually exclusive shells; the list only ever
 * renders under the third:
 *
 * * **Awaiting deploy** — the search endpoint 404s shortly after a release, which
 *   means Vercel published this bundle before Railway finished shipping the
 *   backend. That is a wait, not a failure, so it reads as loading and the hook
 *   retries on a backoff until it resolves.
 * * **Initial error** — the first page failed. This must be an explicit error,
 *   never an empty list: "no jobs found" for what is actually an outage was a
 *   documented follow-up from the 2026-08-10 incident, and it sends the reader
 *   off to change filters that were never the problem.
 * * **Data** — filters, list.
 *
 * There is NO header metric row. One stood above the filters until 2026-09-05,
 * when its three tiles were removed one at a time at the owner's request and the
 * empty shell went with them: "Displayed Jobs" (the server defers the filtered
 * total since #277, so it could only ever show a lower bound over the rows walked
 * — "50+" above fifty cards), then "Past 3 Hours" (a redundant second window),
 * then the row itself. The counts are still fetched and still on the wire —
 * `search.counts` — because page 1 returns them whether or not anything renders
 * them; nothing on this page reads them any more.
 */
export function RecentJobPostingsPage() {
  const search = useRecentJobsSearch();
  const { isAwaitingDeploy, error, errorScope } = search;

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: RESPONSIVE.spacing.pageMarginY }}>
        <Typography
          variant="h3"
          component="h1"
          gutterBottom
          sx={{ fontSize: RESPONSIVE.fontSize.pageTitle }}
        >
          Recent Job Postings
        </Typography>
        <EditCompanyPreferencesRow />

        {isAwaitingDeploy ? (
          <LoadingState caption="Finishing an update — jobs will appear in a moment." />
        ) : (
          <>
            {/* The filters stay mounted through an error on purpose. They are
                persisted across reloads, so when the request failed BECAUSE of
                the filter set (too many companies, too many keywords, a value
                the endpoint rejects), unmounting them leaves the reader with a
                Retry button that reissues the same rejected request forever and
                no way to widen their way out. */}
            <RecentJobsFilters />
            {errorScope === 'initial' && error ? (
              <Box sx={{ mt: 2 }}>
                <ErrorState inline message={error} onRetry={search.retry} />
              </Box>
            ) : (
              <RecentJobsList search={search} />
            )}
          </>
        )}
      </Box>
    </Container>
  );
}
