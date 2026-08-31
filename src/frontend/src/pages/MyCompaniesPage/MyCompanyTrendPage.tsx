import { useMemo, useState } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';
import { useAuth } from '../../features/auth/useAuth';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { EmptyState, ErrorState } from '../../components/shared/ErrorDisplay';
import { TimeWindowSelect } from '../../components/shared/filters/TimeWindowSelect';
import { JobPostingsChart } from '../../components/companies-page/JobPostingsChart/JobPostingsChart';
import { JobList } from '../../components/companies-page/JobList/JobList';
import { bucketJobsByTime } from '../../lib/timeBucketing';
import { extractErrorMessage } from '../../lib/errors';
import { logger } from '../../lib/logger';
import type { Job, TimeWindow } from '../../types';
import {
  useGetUserCompaniesQuery,
  useGetUserCompanyJobsQuery,
} from '../../features/userCompanies/userCompaniesApi';
import { sourceBoardLabel, sourceBoardUrl } from '../../components/my-companies/companyHealth';

/**
 * Default window for a freshly-added board. On day 0 every job shares roughly
 * one `firstSeenAt`, so any window shows a single seed bucket; 30 days gives the
 * axis room to fill in as real day-over-day history accrues.
 */
const DEFAULT_TIME_WINDOW: TimeWindow = '30d';

/** Within-an-hour of the earliest sighting counts as the day-0 seed batch. */
const SEED_WINDOW_MS = 60 * 60 * 1000;

/** firstSeenAt-desc, mirroring `selectGraphFilteredJobsSorted`'s comparator. */
function sortByFirstSeenDesc(jobs: Job[]): Job[] {
  return [...jobs].sort(
    (a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime()
  );
}

/**
 * Count of jobs that were already live when tracking began — the ones whose
 * `firstSeenAt` sits within an hour of the earliest sighting. Phase 1 labels
 * this batch instead of shading it (§2.4), so a brand-new 12k-job board doesn't
 * read as one giant "posted today" spike.
 */
function countSeedJobs(jobs: Job[]): number {
  if (jobs.length === 0) return 0;
  const earliest = Math.min(...jobs.map((job) => new Date(job.firstSeenAt).getTime()));
  return jobs.filter((job) => new Date(job.firstSeenAt).getTime() <= earliest + SEED_WINDOW_MS)
    .length;
}

/** Reads the `:id` param and treats a 403 (owner-scoped) as its own state. */
function is403(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'status' in error &&
    (error as { status: unknown }).status === 403
  );
}

/**
 * Private hiring-trend page for a user-added company.
 *
 * Deliberately self-contained: it fetches jobs by the RUNTIME `:id` via
 * `getUserCompanyJobs` and feeds them straight to the prop-driven leaf
 * components, bypassing the companies-page selector chain
 * (`selectCurrentCompanyJobsRtk` → … → `selectGraphBucketData`) and the
 * `getCompanyById` 404 gate, which are all keyed on compile-time
 * `COMPANY_IDS` and would fail for a `u-…` id.
 */
export function MyCompanyTrendPage() {
  const { id } = useParams<{ id: string }>();
  const { isAuthenticated, isLoading: authLoading, login } = useAuth();
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(DEFAULT_TIME_WINDOW);

  const {
    data: jobs,
    isLoading,
    isFetching,
    isError,
    error,
  } = useGetUserCompanyJobsQuery(id ? { id } : { id: '' }, { skip: !id || !isAuthenticated });

  // THE ROW ITSELF, for the one thing this page has never been able to say: which board
  // it is a trend OF. The page is deliberately jobs-only (see the docstring above), and
  // that is still right for the CHART — but "Hiring trend" over a graph, with no name and
  // no source, is a page you can arrive at and not know what you are looking at. This is
  // the same list the Add Companies page already holds in the RTK Query cache, and the
  // same lookup-by-id `CompanyJobHeader` does; arriving here on a deep link costs one
  // request, and a failure costs nothing because every use of it is optional.
  const { data: userCompanies } = useGetUserCompaniesQuery(undefined, {
    skip: !isAuthenticated,
  });
  // `?.companies?.` and not `?.companies.` — the second `?` is load-bearing. This is an
  // optional garnish on a page whose real payload is the jobs array, so a response that
  // is not the envelope we expect must cost the heading its name, never the chart. With
  // one `?` a body that parses but is not `{ companies }` reads `.find` off `undefined`
  // and takes the whole page down with a TypeError.
  const company = userCompanies?.companies?.find((row) => row.id === id);
  const boardUrl = company ? sourceBoardUrl(company) : null;
  // Both or neither — a link whose text is not derived from its own destination is a
  // link that can lie. See `sourceBoardLabel`.
  const boardLabel = boardUrl ? sourceBoardLabel(boardUrl) : null;

  const sortedJobs = useMemo(() => sortByFirstSeenDesc(jobs ?? []), [jobs]);
  const buckets = useMemo(() => bucketJobsByTime(jobs ?? [], timeWindow), [jobs, timeWindow]);
  const seedCount = useMemo(() => countSeedJobs(jobs ?? []), [jobs]);

  if (authLoading) {
    return <LoadingState fullPage />;
  }

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg, textAlign: 'center' }}>
          <Typography variant="h5" gutterBottom>
            Sign in to view this company
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            Companies you track are private to your account.
          </Typography>
          <Button variant="contained" onClick={login}>
            Sign In
          </Button>
        </Paper>
      </Container>
    );
  }

  const backLink = (
    <Link component={RouterLink} to={ROUTES.MY_COMPANIES} variant="body2">
      ← Back to Add Companies
    </Link>
  );

  return (
    <Container maxWidth="lg" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Stack spacing={3}>
        {backLink}

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h4" component="h1">
              {/* The company's own name when we have it, because "Hiring trend" over a
                  graph with no name is a page you can land on and not know what you are
                  looking at. Falls back to the bare heading rather than a spinner or a
                  placeholder: the chart below is the page, and it does not need the row. */}
              {company ? `${company.displayName} hiring trend` : 'Hiring trend'}
            </Typography>
            {/* AND WHERE IT CAME FROM — the board we actually read to build this, which
                is the question you are asking when a job link turns out to be dead. Only
                when we can name an honest destination; see `sourceBoardUrl`. */}
            {boardUrl && boardLabel ? (
              <Link
                href={boardUrl}
                target="_blank"
                rel="noopener noreferrer"
                variant="body2"
                color="text.secondary"
                underline="hover"
                title={boardUrl}
                data-testid="my-company-board-link"
                sx={{ display: 'inline-block', mt: 0.5, overflowWrap: 'anywhere' }}
              >
                {boardLabel} ↗
              </Link>
            ) : null}
          </Box>
          <TimeWindowSelect value={timeWindow} onChange={setTimeWindow} />
        </Stack>

        {is403(error) ? (
          <ErrorState
            message="This isn't one of your tracked companies, so its jobs aren't visible to you."
            title="Not your company"
          />
        ) : isError ? (
          <ErrorState
            inline
            message={extractErrorMessage(error, "We couldn't load this company's jobs.")}
          />
        ) : isLoading ? (
          <LoadingState minHeight={400} caption="Loading this company's jobs…" />
        ) : sortedJobs.length === 0 ? (
          <EmptyState
            title="Tracking started — no history yet"
            message="We haven't recorded any open jobs for this company yet. Check back after the next run."
          />
        ) : (
          <>
            {seedCount > 0 && (
              <Alert severity="info" data-testid="day-zero-caption">
                <AlertTitle>Tracking just started</AlertTitle>
                {seedCount.toLocaleString()} {seedCount === 1 ? 'opening was' : 'openings were'}{' '}
                already live when tracking began. New postings from here will show as fresh activity
                on the chart.
              </Alert>
            )}

            <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg }}>
              <JobPostingsChart
                data={buckets}
                timeWindow={timeWindow}
                isLoading={isFetching}
                onPointClick={(bucket) =>
                  logger.debug('[MyCompanyTrend] bucket clicked', bucket.bucketStart)
                }
              />
            </Paper>

            <Box>
              <JobList jobs={sortedJobs} />
            </Box>
          </>
        )}
      </Stack>
    </Container>
  );
}
