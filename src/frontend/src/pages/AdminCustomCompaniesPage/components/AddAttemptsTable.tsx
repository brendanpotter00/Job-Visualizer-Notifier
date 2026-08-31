import { Fragment, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ButtonBase from '@mui/material/ButtonBase';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import type { AdminCustomCompanyAttemptRow } from '../../../features/admin/adminApi';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { formatTimestamp, stripScheme } from '../format';
import { attemptOutcomeChip, liveStatusChip } from '../statusChips';
import { AttemptDetail } from './AttemptDetail';

/**
 * Table 2 — one row per ADD ATTEMPT, not per audit row.
 *
 * The `company_add_attempts` table holds roughly two rows per attempt (an
 * interim `discovery_pending` and then a terminal one); the backend collapses
 * them and this table shows the terminal state. Each row expands to the
 * discovery checklist and the audit record — which, for most rows, is the only
 * thing left: deleting a custom company hard-deletes its `companies` row, so
 * the great majority of attempts here point at a board that no longer exists.
 *
 * Desktop expands in place (the `RecentEnrichmentsTable` Collapse pattern);
 * mobile swaps the whole table for a tappable card list whose taps open the
 * SAME detail body in a Dialog.
 */

interface AddAttemptsTableProps {
  attempts: AdminCustomCompanyAttemptRow[];
  /** Attempts matching the current filters, across all pages. Drives the pager. */
  total: number;
  page: number;
  rowsPerPage: number;
  onPageChange: (page: number) => void;
  onRowsPerPageChange: (rowsPerPage: number) => void;
}

/** `user_id` is a soft link with no FK, so render the raw id rather than a blank. */
function userLabel(row: AdminCustomCompanyAttemptRow): string {
  return row.userDisplayName ?? row.userEmail ?? row.userId;
}

/**
 * The Result column: what the attempt actually left behind.
 *
 * Ordered by what the reader most needs: a live board, then a link to a public
 * one, then the failure step, then the fact that the board was deleted.
 */
function ResultCell({ row }: { row: AdminCustomCompanyAttemptRow }) {
  if (row.companyExists && row.companyVisibility === 'public') {
    return (
      <Typography variant="body2" color="text.secondary">
        linked to <strong>{row.companyDisplayName ?? row.companyId}</strong>
      </Typography>
    );
  }
  if (row.companyExists && row.companyDisplayName) {
    const chip = row.companyLiveStatus ? liveStatusChip(row.companyLiveStatus) : null;
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
        <Typography variant="body2">{row.companyDisplayName}</Typography>
        {chip && (
          <Chip size="small" label={chip.label} color={chip.color} variant={chip.variant} />
        )}
      </Box>
    );
  }
  if (row.outcome === 'stuck' || row.outcome === 'pending') {
    return (
      <Typography variant="body2" color="text.secondary">
        {row.outcome === 'stuck' ? 'discovery never finished' : 'discovery in flight'}
      </Typography>
    );
  }
  if (row.failedStep) {
    return (
      <Typography variant="body2">
        {row.failedStep} <Box component="span" sx={{ color: 'error.main' }}>✕</Box>
      </Typography>
    );
  }
  if (row.companyId) {
    return (
      <Typography variant="body2" color="text.disabled">
        since deleted
      </Typography>
    );
  }
  return (
    <Typography variant="body2" color="text.disabled">
      —
    </Typography>
  );
}

/** Mobile: one tappable card per attempt; tap opens the same detail body. */
function MobileAttemptList({
  attempts,
  onSelect,
}: {
  attempts: AdminCustomCompanyAttemptRow[];
  onSelect: (row: AdminCustomCompanyAttemptRow) => void;
}) {
  return (
    <Stack divider={<Box sx={{ borderBottom: 1, borderColor: 'divider' }} />}>
      {attempts.map((row) => {
        const outcome = attemptOutcomeChip(row.outcome);
        return (
          <ButtonBase
            key={row.attemptKey}
            onClick={() => onSelect(row)}
            aria-label={`View attempt for ${row.submittedUrl}`}
            sx={{
              display: 'block',
              textAlign: 'left',
              width: '100%',
              p: 1.5,
              '&:hover': { bgcolor: 'action.hover' },
            }}
          >
            <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, mb: 0.5 }}>
              <Typography variant="body2" sx={{ fontWeight: 500, overflowWrap: 'anywhere' }}>
                {stripScheme(row.submittedUrl)}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                {formatTimestamp(row.createdAt)}
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
              <Typography variant="body2" color="text.secondary">
                {userLabel(row)}
              </Typography>
              <Chip
                size="small"
                label={outcome.label}
                color={outcome.color}
                variant={outcome.variant}
              />
              {row.failedStep && (
                <Typography variant="body2" color="text.secondary">
                  {row.failedStep} ✕
                </Typography>
              )}
            </Box>
          </ButtonBase>
        );
      })}
    </Stack>
  );
}

function AttemptDetailDialog({
  row,
  onClose,
}: {
  row: AdminCustomCompanyAttemptRow | null;
  onClose: () => void;
}) {
  const outcome = row ? attemptOutcomeChip(row.outcome) : null;
  return (
    <Dialog open={row !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Add attempt</DialogTitle>
      <DialogContent dividers>
        {row && outcome && (
          <>
            <Typography variant="body2" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>
              {stripScheme(row.submittedUrl)}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 2, mt: 0.5 }}>
              <Typography variant="caption" color="text.secondary">
                {userLabel(row)} · {formatTimestamp(row.createdAt)}
              </Typography>
              <Chip
                size="small"
                label={outcome.label}
                color={outcome.color}
                variant={outcome.variant}
              />
            </Box>
            <AttemptDetail row={row} />
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

export function AddAttemptsTable({
  attempts,
  total,
  page,
  rowsPerPage,
  onPageChange,
  onRowsPerPageChange,
}: AddAttemptsTableProps) {
  const isMobile = useIsMobile();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selected, setSelected] = useState<AdminCustomCompanyAttemptRow | null>(null);

  // Mandatory on both layouts — see LiveScrapersTable for why.
  const pager = (
    <TablePagination
      component="div"
      count={total}
      page={page}
      onPageChange={(_, p) => onPageChange(p)}
      rowsPerPage={rowsPerPage}
      onRowsPerPageChange={(e) => onRowsPerPageChange(parseInt(e.target.value, 10))}
      rowsPerPageOptions={[25, 50, 100]}
    />
  );

  if (isMobile) {
    return (
      <Box>
        {attempts.length === 0 ? (
          <Typography color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
            No attempts match these filters.
          </Typography>
        ) : (
          <MobileAttemptList attempts={attempts} onSelect={setSelected} />
        )}
        {pager}
        <AttemptDetailDialog row={selected} onClose={() => setSelected(null)} />
      </Box>
    );
  }

  return (
    <Box>
      <TableContainer sx={TABLE_SCROLL_SX}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell width={36} />
              <TableCell>When</TableCell>
              <TableCell>User</TableCell>
              <TableCell>Board URL</TableCell>
              <TableCell>Resolved as</TableCell>
              <TableCell>Outcome</TableCell>
              <TableCell>Result</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {attempts.map((row) => {
              const isOpen = expanded === row.attemptKey;
              const outcome = attemptOutcomeChip(row.outcome);
              return (
                <Fragment key={row.attemptKey}>
                  <TableRow hover>
                    <TableCell padding="none">
                      <IconButton
                        size="small"
                        aria-label={isOpen ? 'Collapse attempt' : 'Expand attempt'}
                        onClick={() => setExpanded(isOpen ? null : row.attemptKey)}
                      >
                        {isOpen ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
                      </IconButton>
                    </TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap', color: 'text.secondary' }}>
                      {formatTimestamp(row.createdAt)}
                    </TableCell>
                    <TableCell sx={{ color: 'text.secondary' }}>{userLabel(row)}</TableCell>
                    <TableCell sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                      {stripScheme(row.submittedUrl)}
                    </TableCell>
                    <TableCell>
                      {row.resolvedAts ? (
                        <Chip size="small" variant="outlined" label={row.resolvedAts} />
                      ) : (
                        <Typography variant="body2" color="text.disabled">
                          —
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={outcome.label}
                        color={outcome.color}
                        variant={outcome.variant}
                      />
                    </TableCell>
                    <TableCell>
                      <ResultCell row={row} />
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell colSpan={7} sx={{ py: 0, border: isOpen ? undefined : 0 }}>
                      <Collapse in={isOpen} unmountOnExit>
                        <Box sx={{ py: 1.5, pl: 4 }}>
                          <AttemptDetail row={row} />
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </Fragment>
              );
            })}
            {attempts.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}>
                  No attempts match these filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
      {pager}
    </Box>
  );
}
