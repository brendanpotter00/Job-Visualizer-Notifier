import { useState, useEffect, useCallback } from 'react';
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
  Paper,
  CircularProgress,
  Alert,
  Link,
  Button,
} from '@mui/material';

type BackendJob = Record<string, unknown>;

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
  const [jobs, setJobs] = useState<BackendJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Scrape-related state
  const [scrapeRuns, setScrapeRuns] = useState<ScrapeRun[]>([]);
  const [scrapeRunsLoading, setScrapeRunsLoading] = useState(true);
  const [scrapeRunsError, setScrapeRunsError] = useState<string | null>(null);
  const [scrapingInProgress, setScrapingInProgress] = useState(false);
  const [scrapeResult, setScrapeResult] = useState<ScraperResult | null>(null);

  useEffect(() => {
    const fetchJobs = async () => {
      try {
        setLoading(true);
        setError(null);
        // Empty status param to get all jobs (no status filter)
        const response = await fetch('/api/jobs?status=');
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        setJobs(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch jobs');
      } finally {
        setLoading(false);
      }
    };

    fetchJobs();
  }, []);

  const fetchScrapeRuns = useCallback(async () => {
    try {
      setScrapeRunsLoading(true);
      setScrapeRunsError(null);
      const response = await fetch('/api/jobs-qa/scrape-runs?limit=20');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      setScrapeRuns(data);
    } catch (err) {
      setScrapeRunsError(
        err instanceof Error ? err.message : 'Failed to fetch scrape runs'
      );
    } finally {
      setScrapeRunsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchScrapeRuns();
  }, [fetchScrapeRuns]);

  const handleTriggerScrape = async () => {
    try {
      setScrapingInProgress(true);
      setScrapeResult(null);
      const response = await fetch('/api/jobs-qa/trigger-scrape?company=google', {
        method: 'POST',
      });
      const data = await response.json();
      setScrapeResult(data);
      // Refresh scrape runs after triggering
      await fetchScrapeRuns();
    } catch (err) {
      setScrapeResult({
        exitCode: -1,
        output: '',
        error: err instanceof Error ? err.message : 'Failed to trigger scrape',
        company: 'google',
        completedAt: new Date().toISOString(),
      });
    } finally {
      setScrapingInProgress(false);
    }
  };

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
            <Button
              variant="contained"
              onClick={handleTriggerScrape}
              disabled={scrapingInProgress}
              startIcon={scrapingInProgress ? <CircularProgress size={20} /> : null}
            >
              {scrapingInProgress ? 'Scraping...' : 'Trigger Scrape (Google)'}
            </Button>
            {scrapeResult && (
              <Alert
                severity={scrapeResult.exitCode === 0 ? 'success' : 'error'}
                sx={{ flexGrow: 1 }}
              >
                {scrapeResult.exitCode === 0
                  ? `Scrape completed successfully for ${scrapeResult.company}`
                  : `Scrape failed: ${scrapeResult.error}`}
              </Alert>
            )}
          </Box>
        </Box>

        {/* Scrape Runs Table */}
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" gutterBottom>
            Scrape Runs
          </Typography>
          {scrapeRunsLoading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', my: 2 }}>
              <CircularProgress size={24} />
            </Box>
          )}
          {scrapeRunsError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {scrapeRunsError}
            </Alert>
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
                  {scrapeRuns.map((run) => (
                    <TableRow key={run.runId}>
                      <TableCell>{run.company}</TableCell>
                      <TableCell>
                        {new Date(run.startedAt).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        {run.completedAt
                          ? new Date(run.completedAt).toLocaleString()
                          : '-'}
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
            </TableContainer>
          )}
        </Box>

        {/* Jobs Table */}
        <Typography variant="h5" gutterBottom>
          All Jobs
        </Typography>
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', my: 4 }}>
            <CircularProgress />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 3 }}>
            {error}
          </Alert>
        )}

        {!loading && !error && (
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Title</TableCell>
                  <TableCell>Company</TableCell>
                  <TableCell>Location</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Last Seen</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow key={String(job.id)}>
                    <TableCell>
                      <Link href={String(job.url)} target="_blank" rel="noopener">
                        {String(job.title)}
                      </Link>
                    </TableCell>
                    <TableCell>{String(job.company)}</TableCell>
                    <TableCell>{job.location ? String(job.location) : '-'}</TableCell>
                    <TableCell>{String(job.status)}</TableCell>
                    <TableCell>{new Date(String(job.lastSeenAt)).toLocaleDateString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>
    </Container>
  );
}
