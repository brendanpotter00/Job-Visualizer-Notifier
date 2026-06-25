import { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import {
  useListProblemJobsQuery,
  useRenormalizeJobMutation,
} from '../../../features/admin/adminApi';
import { LoadingState } from '../../../components/shared/LoadingIndicator';
import { ErrorState } from '../../../components/shared/ErrorDisplay';
import { EmptyState } from '../../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../../lib/errors';
import { TABLE_SCROLL_SX } from '../../../config/responsive';

const PAGE_SIZE = 25;

/** Per-row feedback after a re-normalize attempt. */
type RowFeedback = { kind: 'ok' } | { kind: 'error'; message: string };

export function ProblemJobsTable() {
  const [page, setPage] = useState(0);
  const [feedback, setFeedback] = useState<Record<string, RowFeedback>>({});

  const offset = page * PAGE_SIZE;
  const query = useListProblemJobsQuery({ limit: PAGE_SIZE, offset });
  const [renormalizeJob, renormState] = useRenormalizeJobMutation();

  const jobs = useMemo(() => query.data?.jobs ?? [], [query.data]);
  const total = query.data?.total ?? 0;

  const busyJobId =
    (renormState.isLoading && (renormState.originalArgs?.jobId ?? null)) || null;

  const handleRenormalize = async (jobId: string) => {
    setFeedback((prev) => {
      const next = { ...prev };
      delete next[jobId];
      return next;
    });
    try {
      await renormalizeJob({ jobId }).unwrap();
      setFeedback((prev) => ({ ...prev, [jobId]: { kind: 'ok' } }));
    } catch (err) {
      setFeedback((prev) => ({
        ...prev,
        [jobId]: { kind: 'error', message: extractErrorMessage(err, 'Re-normalize failed') },
      }));
    }
  };

  if (query.isLoading && !query.data) {
    return <LoadingState minHeight={160} caption="Loading problem jobs…" />;
  }
  if (query.error && !query.data) {
    return (
      <ErrorState
        inline
        message={extractErrorMessage(query.error, 'Failed to load problem jobs')}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (jobs.length === 0) {
    return (
      <EmptyState title="No problem jobs" message="No jobs are currently stuck in normalization." />
    );
  }

  return (
    <TableContainer sx={TABLE_SCROLL_SX}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Title</TableCell>
            <TableCell>Company</TableCell>
            <TableCell>Location</TableCell>
            <TableCell>Status</TableCell>
            <TableCell align="right">Action</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {jobs.map((job) => {
            const isBusy = busyJobId === job.id;
            const rowFeedback = feedback[job.id];
            return (
              <TableRow key={job.id} hover>
                <TableCell sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                  {job.id}
                </TableCell>
                <TableCell>{job.title ?? '—'}</TableCell>
                <TableCell>{job.company ?? '—'}</TableCell>
                <TableCell>{job.location ?? '—'}</TableCell>
                <TableCell>
                  {job.normalizationStatus ? (
                    <Chip size="small" variant="outlined" label={job.normalizationStatus} />
                  ) : (
                    '—'
                  )}
                </TableCell>
                <TableCell align="right">
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 1 }}>
                    {rowFeedback?.kind === 'ok' && (
                      <Typography variant="caption" color="success.main">
                        Queued
                      </Typography>
                    )}
                    {rowFeedback?.kind === 'error' && (
                      <Typography variant="caption" color="error.main">
                        {rowFeedback.message}
                      </Typography>
                    )}
                    <Button
                      size="small"
                      onClick={() => handleRenormalize(job.id)}
                      disabled={isBusy}
                      startIcon={isBusy ? <CircularProgress size={14} /> : null}
                    >
                      Re-normalize
                    </Button>
                  </Box>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <TablePagination
        component="div"
        count={total}
        page={page}
        onPageChange={(_, newPage) => setPage(newPage)}
        rowsPerPage={PAGE_SIZE}
        rowsPerPageOptions={[PAGE_SIZE]}
      />
    </TableContainer>
  );
}
