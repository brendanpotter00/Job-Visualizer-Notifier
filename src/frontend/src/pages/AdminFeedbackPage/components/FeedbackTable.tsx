import { useState } from 'react';
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
import ButtonBase from '@mui/material/ButtonBase';
import Stack from '@mui/material/Stack';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import { EmptyState } from '../../../components/shared/ErrorDisplay';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';
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
 * Mobile-only list: each feedback item is a tappable row showing the sender, a
 * 2-line message preview, and the date. Tapping opens the detail modal — full
 * messages are often long, and a wide table is unreadable on a phone.
 */
function MobileFeedbackList({
  feedback,
  onSelect,
}: {
  feedback: FeedbackRow[];
  onSelect: (row: FeedbackRow) => void;
}) {
  return (
    <Stack divider={<Box sx={{ borderBottom: 1, borderColor: 'divider' }} />}>
      {feedback.map((row) => (
        <ButtonBase
          key={row.id}
          onClick={() => onSelect(row)}
          aria-label={`View feedback from ${row.displayName ?? row.userEmail ?? 'anonymous'}`}
          sx={{
            display: 'block',
            textAlign: 'left',
            width: '100%',
            p: 1.5,
            '&:hover': { bgcolor: 'action.hover' },
          }}
        >
          <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, mb: 0.5 }}>
            <FromCell row={row} />
            <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
              {formatSubmitted(row.createdAt)}
            </Typography>
          </Box>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {row.message}
          </Typography>
        </ButtonBase>
      ))}
    </Stack>
  );
}

/** Detail modal for a single feedback item (mobile). Closed = renders nothing visible. */
function FeedbackDetailDialog({ row, onClose }: { row: FeedbackRow | null; onClose: () => void }) {
  return (
    <Dialog open={row !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Feedback</DialogTitle>
      <DialogContent dividers>
        {row && (
          <>
            <FromCell row={row} />
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
              {formatSubmitted(row.createdAt)}
            </Typography>
            <Typography sx={{ whiteSpace: 'pre-wrap' }}>{row.message}</Typography>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

/**
 * Presentational table for the admin feedback viewer. Pagination and sort are
 * controlled by the parent (which turns them into a server query), so this
 * component only renders the page it is handed — no client-side slicing.
 *
 * On mobile the wide table is replaced by a tappable list whose items open a
 * detail modal; desktop (>= 600px) keeps the table byte-for-byte.
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
  const isMobile = useIsMobile();
  const [selected, setSelected] = useState<FeedbackRow | null>(null);

  if (total === 0) {
    return <EmptyState title="No feedback yet" message="No feedback has been submitted." />;
  }

  if (isMobile) {
    return (
      <Paper variant="outlined">
        <MobileFeedbackList feedback={feedback} onSelect={setSelected} />
        <TablePagination
          component="div"
          count={total}
          page={page}
          onPageChange={(_, p) => onPageChange(p)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e) => onRowsPerPageChange(parseInt(e.target.value, 10))}
          rowsPerPageOptions={[25, 50, 100]}
        />
        <FeedbackDetailDialog row={selected} onClose={() => setSelected(null)} />
      </Paper>
    );
  }

  return (
    <Paper variant="outlined">
      <TableContainer sx={TABLE_SCROLL_SX}>
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
