import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import TableSortLabel from '@mui/material/TableSortLabel';
import { EmptyState } from '../../../components/shared/ErrorDisplay';
import type { FeedbackRow } from '../../../features/admin/adminApi';

type SortDir = 'asc' | 'desc';

interface FeedbackTableProps {
  /** The current page of rows, already ordered server-side. */
  feedback: FeedbackRow[];
  /** Total rows across the whole table (drives the pager). */
  total: number;
  page: number;
  rowsPerPage: number;
  sortDir: SortDir;
  onPageChange: (page: number) => void;
  onRowsPerPageChange: (rowsPerPage: number) => void;
  onToggleSort: () => void;
}

function formatSubmitted(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

function FromCell({ row }: { row: FeedbackRow }) {
  // Identity is shown from the point-in-time snapshot (userEmail/displayName),
  // not userId — so a row whose FK was nulled by ON DELETE SET NULL still shows
  // who submitted it. A row with neither snapshot field is a true anonymous
  // submission (the backend always snapshots email alongside user_id).
  if (!row.userEmail && !row.displayName) {
    return (
      <Typography component="span" color="text.disabled">
        Anonymous
      </Typography>
    );
  }
  return (
    <Box>
      <Typography variant="body2">{row.displayName ?? row.userEmail}</Typography>
      {row.displayName && row.userEmail && (
        <Typography variant="caption" color="text.secondary">
          {row.userEmail}
        </Typography>
      )}
    </Box>
  );
}

/**
 * Presentational table for the admin feedback viewer. Pagination and sort are
 * controlled by the parent (which turns them into a server query), so this
 * component only renders the page it is handed — no client-side slicing.
 */
export function FeedbackTable({
  feedback,
  total,
  page,
  rowsPerPage,
  sortDir,
  onPageChange,
  onRowsPerPageChange,
  onToggleSort,
}: FeedbackTableProps) {
  if (total === 0) {
    return <EmptyState title="No feedback yet" message="No feedback has been submitted." />;
  }

  return (
    <Paper variant="outlined">
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ minWidth: 160 }}>From</TableCell>
              <TableCell>Message</TableCell>
              <TableCell align="right" sortDirection={sortDir}>
                <TableSortLabel
                  active
                  direction={sortDir}
                  onClick={onToggleSort}
                >
                  Submitted
                </TableSortLabel>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {feedback.map((row) => (
              <TableRow key={row.id} hover>
                <TableCell>
                  <FromCell row={row} />
                </TableCell>
                <TableCell sx={{ whiteSpace: 'pre-wrap', maxWidth: 640 }}>
                  {row.message}
                </TableCell>
                <TableCell
                  align="right"
                  sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}
                >
                  {formatSubmitted(row.createdAt)}
                </TableCell>
              </TableRow>
            ))}
            {feedback.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={3}
                  sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}
                >
                  No feedback on this page.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePagination
        component="div"
        count={total}
        page={page}
        onPageChange={(_, p) => onPageChange(p)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(e) => onRowsPerPageChange(parseInt(e.target.value, 10))}
        rowsPerPageOptions={[25, 50, 100]}
      />
    </Paper>
  );
}
