import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ButtonBase from '@mui/material/ButtonBase';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import type { AdminCustomCompanyRow } from '../../../features/admin/adminApi';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { formatAge } from '../../AdminEnrichmentPage/verdict';
import { formatTimestamp } from '../format';
import { healthStateChip, liveStatusChip } from '../statusChips';

/**
 * Table 1 — the boards users added themselves, and whether each one is
 * ACTUALLY harvesting.
 *
 * "Live" is not "a row exists": it is enabled AND the newest harvest was not
 * FAILED AND it returned more than zero records AND it ran inside twice its
 * cadence. That rule is evaluated once, server-side, so this column and the
 * StatTile above it cannot disagree — the component only renders what it is
 * handed.
 *
 * Presentational: pagination and filters are controlled by the page, which
 * turns them into a server query. Nothing here slices a fetched array.
 */

interface LiveScrapersTableProps {
  companies: AdminCustomCompanyRow[];
  /** Rows matching the current filters, across all pages. Drives the pager. */
  total: number;
  page: number;
  rowsPerPage: number;
  onPageChange: (page: number) => void;
  onRowsPerPageChange: (rowsPerPage: number) => void;
}

/** The owner cell / line. An unowned board is a real state, so it says so. */
function OwnerLabel({ row }: { row: AdminCustomCompanyRow }) {
  if (row.ownerCount === 0) {
    return (
      <Typography component="span" variant="body2" color="text.disabled">
        — no owner row —
      </Typography>
    );
  }
  return (
    <Typography component="span" variant="body2" color="text.secondary">
      {/* `user_companies` links by id with no snapshot, so a deleted user
          leaves the id as the only thing left to show. Never blank the cell. */}
      {row.ownerEmail ?? row.ownerDisplayName ?? row.ownerUserId ?? '—'}
      {row.ownerCount > 1 ? ` (+${row.ownerCount - 1} shared)` : ''}
    </Typography>
  );
}

function JobsCell({ row }: { row: AdminCustomCompanyRow }) {
  if (row.recordsHarvested === null) {
    return (
      <Typography variant="body2" color="text.disabled">
        —
      </Typography>
    );
  }
  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {row.recordsHarvested.toLocaleString()}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {row.capHit ? 'cap hit' : 'open'}
      </Typography>
    </Box>
  );
}

function LastHarvestCell({ row }: { row: AdminCustomCompanyRow }) {
  if (row.lastHarvestAt === null) {
    return (
      <Typography variant="body2" color="text.disabled">
        never
      </Typography>
    );
  }
  return (
    <Box>
      <Typography variant="body2" color="text.secondary">
        {formatTimestamp(row.lastHarvestAt)}
      </Typography>
      {row.lastHarvestAgeS !== null && (
        <Typography variant="caption" color="text.disabled">
          {formatAge(row.lastHarvestAgeS)} ago
        </Typography>
      )}
    </Box>
  );
}

/**
 * The Live? chip. `liveReason` rides along as the tooltip rather than a second
 * line: on a healthy page every row would otherwise carry an explanation of a
 * state that needs none.
 */
function LiveChip({ row }: { row: AdminCustomCompanyRow }) {
  const chip = liveStatusChip(row.liveStatus);
  const element = (
    <Chip size="small" label={chip.label} color={chip.color} variant={chip.variant} />
  );
  return row.liveReason ? (
    <Tooltip title={row.liveReason} placement="top">
      <span>{element}</span>
    </Tooltip>
  ) : (
    element
  );
}

/** Mobile: one tappable card per board; tap opens the full record. */
function MobileScraperList({
  companies,
  onSelect,
}: {
  companies: AdminCustomCompanyRow[];
  onSelect: (row: AdminCustomCompanyRow) => void;
}) {
  return (
    <Stack divider={<Box sx={{ borderBottom: 1, borderColor: 'divider' }} />}>
      {companies.map((row) => {
        const live = liveStatusChip(row.liveStatus);
        const health = healthStateChip(row.healthState);
        return (
          <ButtonBase
            key={row.id}
            onClick={() => onSelect(row)}
            aria-label={`View ${row.displayName}`}
            sx={{
              display: 'block',
              textAlign: 'left',
              width: '100%',
              p: 1.5,
              '&:hover': { bgcolor: 'action.hover' },
            }}
          >
            <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, mb: 0.5 }}>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {row.displayName}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
                {row.lastHarvestAgeS === null ? 'never' : `${formatAge(row.lastHarvestAgeS)} ago`}
              </Typography>
            </Box>
            <Typography variant="body2" color="text.secondary">
              <OwnerLabel row={row} />
              {row.recordsHarvested !== null
                ? ` · ${row.recordsHarvested.toLocaleString()} jobs`
                : ''}
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, mt: 0.75, flexWrap: 'wrap' }}>
              <Chip size="small" label={live.label} color={live.color} variant={live.variant} />
              <Chip
                size="small"
                label={health.label}
                color={health.color}
                variant={health.variant}
              />
            </Box>
          </ButtonBase>
        );
      })}
    </Stack>
  );
}

/** The full board record — the columns the phone had to drop, plus the rest. */
function ScraperDetailDialog({
  row,
  onClose,
}: {
  row: AdminCustomCompanyRow | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={row !== null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{row?.displayName ?? 'Board'}</DialogTitle>
      <DialogContent dividers>
        {row && (
          <Box>
            <Typography
              variant="caption"
              color="text.secondary"
              display="block"
              sx={{ fontFamily: 'monospace', mb: 1 }}
            >
              {row.id}
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1.5 }}>
              <LiveChip row={row} />
              <Chip
                size="small"
                label={healthStateChip(row.healthState).label}
                color={healthStateChip(row.healthState).color}
                variant={healthStateChip(row.healthState).variant}
              />
            </Box>
            {row.liveReason && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                {row.liveReason}
              </Typography>
            )}
            <Typography variant="body2" sx={{ mb: 0.5 }}>
              Owner <OwnerLabel row={row} />
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              ATS {row.ats} · transport {row.transport ?? '—'} · script v
              {row.scriptVersion ?? '—'}
            </Typography>
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ mb: 0.5, overflowWrap: 'anywhere' }}
            >
              Board token {row.boardToken}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Last harvest {formatTimestamp(row.lastHarvestAt)} · verdict {row.verdict ?? '—'}
              {row.verdictReason ? ` (${row.verdictReason})` : ''}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Records {row.recordsHarvested?.toLocaleString() ?? '—'} · declared{' '}
              {row.declaredTotal?.toLocaleString() ?? '—'} · oracle{' '}
              {row.oracleTotal?.toLocaleString() ?? '—'}
              {row.capHit ? ' · cap hit' : ''}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Cadence {row.cadenceHours ?? '—'} h · {row.consecutiveFailures} consecutive
              failure(s) · added {formatTimestamp(row.createdAt)}
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

export function LiveScrapersTable({
  companies,
  total,
  page,
  rowsPerPage,
  onPageChange,
  onRowsPerPageChange,
}: LiveScrapersTableProps) {
  const isMobile = useIsMobile();
  const [selected, setSelected] = useState<AdminCustomCompanyRow | null>(null);

  // Pagination is rendered on BOTH layouts and is never optional: an
  // unpaginated admin table is what produced this repo's 50 GB Chrome session
  // (root CLAUDE.md gotcha #7).
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
        {companies.length === 0 ? (
          <Typography color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
            No boards match these filters.
          </Typography>
        ) : (
          <MobileScraperList companies={companies} onSelect={setSelected} />
        )}
        {pager}
        <ScraperDetailDialog row={selected} onClose={() => setSelected(null)} />
      </Box>
    );
  }

  return (
    <Box>
      <TableContainer sx={TABLE_SCROLL_SX}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Company</TableCell>
              <TableCell>Owner</TableCell>
              <TableCell>Health</TableCell>
              <TableCell>Transport</TableCell>
              <TableCell>Last harvest</TableCell>
              <TableCell align="right">Jobs</TableCell>
              <TableCell>Live?</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {companies.map((row) => {
              const health = healthStateChip(row.healthState);
              return (
                <TableRow key={row.id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {row.displayName}
                    </Typography>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ fontFamily: 'monospace' }}
                    >
                      {row.id}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <OwnerLabel row={row} />
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={health.label}
                      color={health.color}
                      variant={health.variant}
                    />
                  </TableCell>
                  <TableCell>
                    {row.transport ? (
                      <Chip size="small" variant="outlined" label={row.transport} />
                    ) : (
                      <Typography variant="body2" color="text.disabled">
                        —
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    <LastHarvestCell row={row} />
                  </TableCell>
                  <TableCell align="right">
                    <JobsCell row={row} />
                  </TableCell>
                  <TableCell>
                    <LiveChip row={row} />
                  </TableCell>
                </TableRow>
              );
            })}
            {companies.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}>
                  No boards match these filters.
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
