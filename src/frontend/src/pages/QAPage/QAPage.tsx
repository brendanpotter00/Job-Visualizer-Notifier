import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Container,
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Paper,
  CircularProgress,
  Alert,
  Link,
  Button,
  TablePagination,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Stack,
} from '@mui/material';
import { SearchTagsInput } from '../../components/shared/filters/SearchTagsInput.tsx';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { useFetchWithStatus } from '../../hooks/useFetchWithStatus';
import { extractErrorMessage } from '../../lib/errors';
import { useAuth, NotAuthenticatedError } from '../../features/auth/useAuth';
import type { SearchTag } from '../../types/index.ts';
import type { BackendJobListing } from '../../api/types.ts';
import { COMPANIES } from '../../config/companies';

// Backend scraper companies for QA filtering
const BACKEND_SCRAPER_COMPANIES = COMPANIES.filter((c) => c.ats === 'backend-scraper');

type QACompanySelection = 'all' | string;

type SortableJobField = 'title' | 'company' | 'location' | 'status' | 'firstSeenAt' | 'lastSeenAt' | 'postedOn';

interface ScrapeRun {
  runId: string;
  company: string;
  startedAt: string;
  completedAt: string | null;
  mode: string;
  jobsSeen: number;
  newJobs: number;
  closedJobs: number;
  detailsFetched: number;
  errorCount: number;
}

interface ScraperResult {
  exitCode: number;
  output: string;
  error: string;
  company: string;
  completedAt: string;
}

/**
 * QAPage - Development-only page for viewing all jobs from the backend
 *
 * Features:
 * - Fetches all jobs from /api/jobs endpoint
 * - Displays jobs in a table with key fields
 * - Only visible in development mode
 *
 * @returns QA page component
 */
export function QAPage() {
  // Bearer token is required for /api/jobs-qa/*: the backend gates those
  // endpoints behind require_admin, so unauthenticated requests return 401.
  // AdminRoute already ensures only signed-in admins reach this page.
  const { getToken } = useAuth();

  // Scrape-related state
  const [scrapingInProgress, setScrapingInProgress] = useState(false);
  const [scrapeResult, setScrapeResult] = useState<ScraperResult | null>(null);

  // Jobs filter state
  const [searchTags, setSearchTags] = useState<SearchTag[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // Scrape runs pagination state
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);

  // Jobs table pagination state
  const [jobsPage, setJobsPage] = useState(0);
  const [jobsRowsPerPage, setJobsRowsPerPage] = useState(25);

  // Company filter state
  const [selectedCompany, setSelectedCompany] = useState<QACompanySelection>('all');

  // Jobs sort state
  const [sortBy, setSortBy] = useState<SortableJobField>('lastSeenAt');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  const handleSort = (field: SortableJobField) => {
    if (sortBy === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(field);
      setSortDirection('asc');
    }
  };

  const fetchJobsRequest = useCallback(
    async (signal: AbortSignal): Promise<BackendJobListing[]> => {
      const params = new URLSearchParams();
      if (selectedCompany !== 'all') params.set('company', selectedCompany);
      const response = await fetch(`/api/jobs?${params}`, { signal });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    },
    [selectedCompany]
  );
  const {
    data: jobsData,
    loading,
    error,
  } = useFetchWithStatus<BackendJobListing[]>({
    fetcher: fetchJobsRequest,
    deps: [selectedCompany],
  });
  const jobs = useMemo(() => jobsData ?? [], [jobsData]);

  const fetchScrapeRunsRequest = useCallback(
    async (signal: AbortSignal): Promise<ScrapeRun[]> => {
      const companyParam = selectedCompany !== 'all' ? `&company=${selectedCompany}` : '';
      // ``getToken()`` throws ``NotAuthenticatedError`` on signed-out renders
      // (the normal anonymous path). AdminRoute is what guarantees we never
      // reach this page anonymously in production, but the brief
      // signed-out frame on logout / first render would otherwise flash a
      // "Not authenticated" page error before the redirect lands.
      // Short-circuit on the marker class and return [] — every other
      // error (token-refresh failure, network) must still propagate.
      let token: string;
      try {
        token = await getToken();
      } catch (err) {
        if (err instanceof NotAuthenticatedError) return [];
        throw err;
      }
      const response = await fetch(
        `/api/jobs-qa/scrape-runs?limit=100${companyParam}`,
        {
          signal,
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    },
    [selectedCompany, getToken]
  );
  const {
    data: scrapeRunsData,
    loading: scrapeRunsLoading,
    error: scrapeRunsError,
    reload: reloadScrapeRuns,
  } = useFetchWithStatus<ScrapeRun[]>({
    fetcher: fetchScrapeRunsRequest,
    deps: [selectedCompany],
  });
  const scrapeRuns = useMemo(() => scrapeRunsData ?? [], [scrapeRunsData]);

  const handleTriggerScrape = async () => {
    // Guard: require specific company selection
    if (selectedCompany === 'all') {
      return;
    }

    try {
      setScrapingInProgress(true);
      setScrapeResult(null);
      let token: string;
      try {
        token = await getToken();
      } catch (err) {
        if (err instanceof NotAuthenticatedError) {
          // Anonymous click should never happen (AdminRoute guards this
          // page). When it DOES happen (mid-session expiry, signed-out
          // race), the user clicks "Trigger Scrape" and previously saw
          // nothing — silent failure. Surface an actionable warning via
          // the scrapeResult Alert so the admin knows to re-auth instead
          // of staring at an unresponsive button.
          setScrapeResult({
            exitCode: -1,
            output: '',
            error: 'Your session expired — please sign back in.',
            company: selectedCompany,
            completedAt: new Date().toISOString(),
          });
          return;
        }
        throw err;
      }
      const response = await fetch(`/api/jobs-qa/trigger-scrape?company=${selectedCompany}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });

      // Handle HTTP errors BEFORE attempting to parse JSON (like backendScraperClient)
      if (!response.ok) {
        // Try to get error details from JSON response (safe for API errors)
        let errorMessage = `Request failed: ${response.status} ${response.statusText}`;
        try {
          const errorData = await response.json();
          if (errorData.error) {
            errorMessage = errorData.error;
          }
        } catch {
          // Non-JSON response, use status text
        }
        setScrapeResult({
          exitCode: -1,
          output: '',
          error: errorMessage,
          company: selectedCompany,
          completedAt: new Date().toISOString(),
        });
        return;
      }

      // Only parse JSON for successful responses
      const data = await response.json();

      // Handle 202 Accepted (scrape started in background)
      if (response.status === 202) {
        setScrapeResult({
          exitCode: 0,
          output: data.message || 'Scrape started',
          error: '',
          company: data.company || selectedCompany,
          completedAt: new Date().toISOString(),
        });
      } else {
        setScrapeResult(data);
      }

      // Refresh scrape runs after triggering (via useFetchWithStatus reload).
      reloadScrapeRuns();
    } catch (err) {
      setScrapeResult({
        exitCode: -1,
        output: '',
        error: extractErrorMessage(err, 'Failed to trigger scrape'),
        company: selectedCompany,
        completedAt: new Date().toISOString(),
      });
    } finally {
      setScrapingInProgress(false);
    }
  };

  // Filter jobs based on search tags and status
  const filteredJobs = useMemo(() => {
    return jobs.filter((job) => {
      // Status filter
      if (statusFilter !== 'all' && job.status !== statusFilter) {
        return false;
      }

      // Search tags filter
      if (searchTags.length > 0) {
        const searchableText = [job.title, job.company, job.location ?? '']
          .join(' ')
          .toLowerCase();

        const includeTags = searchTags.filter((t) => t.mode === 'include');
        const excludeTags = searchTags.filter((t) => t.mode === 'exclude');

        // Include: at least one must match (OR logic)
        if (includeTags.length > 0) {
          const hasIncludeMatch = includeTags.some((tag) =>
            searchableText.includes(tag.text.toLowerCase())
          );
          if (!hasIncludeMatch) return false;
        }

        // Exclude: none must match (AND NOT logic)
        if (excludeTags.length > 0) {
          const hasExcludeMatch = excludeTags.some((tag) =>
            searchableText.includes(tag.text.toLowerCase())
          );
          if (hasExcludeMatch) return false;
        }
      }

      return true;
    });
  }, [jobs, statusFilter, searchTags]);

  // Sort filtered jobs
  const sortedJobs = useMemo(() => {
    return [...filteredJobs].sort((a, b) => {
      const aVal = a[sortBy];
      const bVal = b[sortBy];

      // Handle null values (push to end)
      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;

      // Handle date fields
      if (sortBy === 'firstSeenAt' || sortBy === 'lastSeenAt' || sortBy === 'postedOn') {
        const aTime = new Date(aVal as string).getTime();
        const bTime = new Date(bVal as string).getTime();
        return sortDirection === 'asc' ? aTime - bTime : bTime - aTime;
      }

      // Handle string fields
      const comparison = String(aVal).localeCompare(String(bVal));
      return sortDirection === 'asc' ? comparison : -comparison;
    });
  }, [filteredJobs, sortBy, sortDirection]);

  // Paginate jobs table
  const paginatedJobs = useMemo(() => {
    const start = jobsPage * jobsRowsPerPage;
    return sortedJobs.slice(start, start + jobsRowsPerPage);
  }, [sortedJobs, jobsPage, jobsRowsPerPage]);

  // Reset jobs page when filters change
  useEffect(() => {
    setJobsPage(0);
  }, [searchTags, statusFilter, selectedCompany]);

  // Paginate scrape runs
  const paginatedRuns = useMemo(() => {
    const start = page * rowsPerPage;
    return scrapeRuns.slice(start, start + rowsPerPage);
  }, [scrapeRuns, page, rowsPerPage]);

  // Handlers for search tags
  const handleAddTag = useCallback((tag: SearchTag) => {
    setSearchTags((prev) => [...prev, tag]);
  }, []);

  const handleRemoveTag = useCallback((text: string) => {
    setSearchTags((prev) => prev.filter((t) => t.text !== text));
  }, []);

  const handleToggleTagMode = useCallback((text: string) => {
    setSearchTags((prev) =>
      prev.map((t) =>
        t.text === text ? { ...t, mode: t.mode === 'include' ? 'exclude' : 'include' } : t
      )
    );
  }, []);

  return (
    <Container maxWidth={false} sx={{ px: { xs: 2, sm: 3, md: 4 } }}>
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          QA - All Jobs
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
          Showing all jobs from the backend database ({jobs.length} total)
        </Typography>

        {/* Scrape Controls */}
        <Box sx={{ mb: 4, p: 2, bgcolor: 'background.paper', borderRadius: 1 }}>
          <Typography variant="h5" gutterBottom>
            Scrape Controls
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel id="company-filter-label">Company</InputLabel>
              <Select
                labelId="company-filter-label"
                value={selectedCompany}
                label="Company"
                onChange={(e) => setSelectedCompany(e.target.value as QACompanySelection)}
              >
                <MenuItem value="all">All Companies</MenuItem>
                {BACKEND_SCRAPER_COMPANIES.map((company) => (
                  <MenuItem key={company.id} value={company.id}>
                    {company.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              onClick={handleTriggerScrape}
              disabled={scrapingInProgress || selectedCompany === 'all'}
              startIcon={scrapingInProgress ? <CircularProgress size={20} /> : null}
            >
              {scrapingInProgress
                ? 'Scraping...'
                : selectedCompany === 'all'
                  ? 'Select Company to Scrape'
                  : `Trigger Scrape (${BACKEND_SCRAPER_COMPANIES.find((c) => c.id === selectedCompany)?.name})`}
            </Button>
            {scrapeResult && (
              <Alert
                severity={scrapeResult.exitCode === 0 ? 'success' : 'error'}
                sx={{ flexGrow: 1 }}
              >
                {scrapeResult.exitCode === 0
                  ? scrapeResult.output || `Scrape started for ${scrapeResult.company}`
                  : `Scrape failed: ${scrapeResult.error}`}
              </Alert>
            )}
          </Box>
        </Box>

        {/* Scrape Runs Table */}
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" gutterBottom>
            {selectedCompany === 'all'
              ? 'Scrape Runs'
              : `${BACKEND_SCRAPER_COMPANIES.find((c) => c.id === selectedCompany)?.name} Scrape Runs`}
          </Typography>
          {scrapeRunsLoading && <LoadingState size={24} minHeight={48} />}
          {scrapeRunsError && (
            <Box sx={{ mb: 2 }}>
              <ErrorState inline message={scrapeRunsError} />
            </Box>
          )}
          {!scrapeRunsLoading && !scrapeRunsError && (
            <TableContainer component={Paper}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Company</TableCell>
                    <TableCell>Started At</TableCell>
                    <TableCell>Completed At</TableCell>
                    <TableCell>Mode</TableCell>
                    <TableCell align="right">Jobs Seen</TableCell>
                    <TableCell align="right">New</TableCell>
                    <TableCell align="right">Closed</TableCell>
                    <TableCell align="right">Details</TableCell>
                    <TableCell align="right">Errors</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {paginatedRuns.map((run) => (
                    <TableRow key={run.runId}>
                      <TableCell>{run.company}</TableCell>
                      <TableCell>{new Date(run.startedAt).toLocaleString()}</TableCell>
                      <TableCell>
                        {run.completedAt ? new Date(run.completedAt).toLocaleString() : '-'}
                      </TableCell>
                      <TableCell>{run.mode}</TableCell>
                      <TableCell align="right">{run.jobsSeen}</TableCell>
                      <TableCell align="right">{run.newJobs}</TableCell>
                      <TableCell align="right">{run.closedJobs}</TableCell>
                      <TableCell align="right">{run.detailsFetched}</TableCell>
                      <TableCell align="right">{run.errorCount}</TableCell>
                    </TableRow>
                  ))}
                  {scrapeRuns.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={9} align="center">
                        No scrape runs found
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
              <TablePagination
                component="div"
                count={scrapeRuns.length}
                page={page}
                onPageChange={(_, newPage) => setPage(newPage)}
                rowsPerPage={rowsPerPage}
                onRowsPerPageChange={(e) => {
                  setRowsPerPage(parseInt(e.target.value, 10));
                  setPage(0);
                }}
                rowsPerPageOptions={[10, 25, 50]}
              />
            </TableContainer>
          )}
        </Box>

        {/* Jobs Table */}
        <Typography variant="h5" gutterBottom>
          {selectedCompany === 'all'
            ? 'All Jobs'
            : `${BACKEND_SCRAPER_COMPANIES.find((c) => c.id === selectedCompany)?.name} Jobs`}
        </Typography>

        {/* Jobs Filters */}
        <Box sx={{ mb: 3 }}>
          <Stack spacing={2}>
            <SearchTagsInput
              value={searchTags}
              onAdd={handleAddTag}
              onRemove={handleRemoveTag}
              onToggleMode={handleToggleTagMode}
            />
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel id="status-filter-label">Status</InputLabel>
                <Select
                  labelId="status-filter-label"
                  value={statusFilter}
                  label="Status"
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <MenuItem value="all">All</MenuItem>
                  <MenuItem value="OPEN">Open</MenuItem>
                  <MenuItem value="CLOSED">Closed</MenuItem>
                </Select>
              </FormControl>
              <Typography variant="body2" color="text.secondary">
                Showing {filteredJobs.length} of {jobs.length} jobs
              </Typography>
            </Stack>
          </Stack>
        </Box>

        {loading && <LoadingState minHeight={96} />}

        {error && (
          <Box sx={{ mb: 3 }}>
            <ErrorState inline message={error} />
          </Box>
        )}

        {!loading && !error && (
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>
                    <TableSortLabel
                      active={sortBy === 'title'}
                      direction={sortBy === 'title' ? sortDirection : 'asc'}
                      onClick={() => handleSort('title')}
                    >
                      Title
                    </TableSortLabel>
                  </TableCell>
                  <TableCell>
                    <TableSortLabel
                      active={sortBy === 'company'}
                      direction={sortBy === 'company' ? sortDirection : 'asc'}
                      onClick={() => handleSort('company')}
                    >
                      Company
                    </TableSortLabel>
                  </TableCell>
                  <TableCell>
                    <TableSortLabel
                      active={sortBy === 'location'}
                      direction={sortBy === 'location' ? sortDirection : 'asc'}
                      onClick={() => handleSort('location')}
                    >
                      Location
                    </TableSortLabel>
                  </TableCell>
                  <TableCell>
                    <TableSortLabel
                      active={sortBy === 'status'}
                      direction={sortBy === 'status' ? sortDirection : 'asc'}
                      onClick={() => handleSort('status')}
                    >
                      Status
                    </TableSortLabel>
                  </TableCell>
                  <TableCell>
                    <TableSortLabel
                      active={sortBy === 'firstSeenAt'}
                      direction={sortBy === 'firstSeenAt' ? sortDirection : 'asc'}
                      onClick={() => handleSort('firstSeenAt')}
                    >
                      First Seen
                    </TableSortLabel>
                  </TableCell>
                  <TableCell>
                    <TableSortLabel
                      active={sortBy === 'lastSeenAt'}
                      direction={sortBy === 'lastSeenAt' ? sortDirection : 'asc'}
                      onClick={() => handleSort('lastSeenAt')}
                    >
                      Last Seen
                    </TableSortLabel>
                  </TableCell>
                  <TableCell>
                    <TableSortLabel
                      active={sortBy === 'postedOn'}
                      direction={sortBy === 'postedOn' ? sortDirection : 'asc'}
                      onClick={() => handleSort('postedOn')}
                    >
                      Posted On
                    </TableSortLabel>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {paginatedJobs.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell>
                      <Link href={job.url} target="_blank" rel="noopener">
                        {job.title}
                      </Link>
                    </TableCell>
                    <TableCell>{job.company}</TableCell>
                    <TableCell>{job.location ?? '-'}</TableCell>
                    <TableCell>{job.status}</TableCell>
                    <TableCell>{new Date(job.firstSeenAt).toLocaleDateString()}</TableCell>
                    <TableCell>{new Date(job.lastSeenAt).toLocaleDateString()}</TableCell>
                    <TableCell>
                      {job.postedOn ? new Date(job.postedOn).toLocaleDateString() : '-'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
              <TablePagination
                component="div"
                count={sortedJobs.length}
                page={jobsPage}
                onPageChange={(_, newPage) => setJobsPage(newPage)}
                rowsPerPage={jobsRowsPerPage}
                onRowsPerPageChange={(e) => {
                  setJobsRowsPerPage(parseInt(e.target.value, 10));
                  setJobsPage(0);
                }}
                rowsPerPageOptions={[25, 50, 100, 250]}
              />
          </TableContainer>
        )}
      </Box>
    </Container>
  );
}
