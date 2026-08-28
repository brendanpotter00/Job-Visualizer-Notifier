import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import type { AdminCustomCompanyUserRow } from '../../../features/admin/adminApi';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { formatDay } from '../format';
import type { ChipColor } from '../statusChips';

/**
 * Table 3 — who is actually using this, rolled up from the same attempts CTE
 * Table 2 renders row by row.
 *
 * The rollup is ALWAYS unfiltered (it also feeds the User dropdown above, so
 * it must not shrink as you filter by user) and ships whole in the attempts
 * response, capped server-side. Pagination is therefore CLIENT-side here —
 * still mandatory, still 25 by default: the cap is 200 rows and the rule is
 * that no admin table renders unbounded (root CLAUDE.md gotcha #7).
 *
 * "Owns now" is deliberately its own column rather than a synonym for "Added":
 * deleting a custom company hard-deletes its `companies` row, so a user with
 * seventeen successful adds can own two boards. That gap is the single most
 * useful number on the page.
 */

interface UsersRollupTableProps {
  users: AdminCustomCompanyUserRow[];
  /** true when the server-side rollup hit its cap and this is not everyone. */
  usersTruncated: boolean;
  page: number;
  rowsPerPage: number;
  onPageChange: (page: number) => void;
  onRowsPerPageChange: (rowsPerPage: number) => void;
}

/**
 * A count cell. Zero renders as plain grey text rather than a chip: a solid red
 * "0" would shout severity at the absence of the thing it is severe about.
 */
function CountCell({
  value,
  color,
  variant,
}: {
  value: number;
  color: ChipColor;
  variant: 'filled' | 'outlined';
}) {
  if (value === 0) {
    return (
      <Typography variant="body2" color="text.disabled">
        0
      </Typography>
    );
  }
  return <Chip size="small" label={value.toLocaleString()} color={color} variant={variant} />;
}

function userLabel(row: AdminCustomCompanyUserRow): string {
  // Soft link, no FK — a deleted user leaves only the id, and the id is still
  // more useful than an empty cell.
  return row.email ?? row.displayName ?? row.userId;
}

export function UsersRollupTable({
  users,
  usersTruncated,
  page,
  rowsPerPage,
  onPageChange,
  onRowsPerPageChange,
}: UsersRollupTableProps) {
  const isMobile = useIsMobile();
  // Client-side slice, unlike the other two tables: this payload arrives whole.
  const visible = users.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

  const pager = (
    <TablePagination
      component="div"
      count={users.length}
      page={page}
      onPageChange={(_, p) => onPageChange(p)}
      rowsPerPage={rowsPerPage}
      onRowsPerPageChange={(e) => onRowsPerPageChange(parseInt(e.target.value, 10))}
      rowsPerPageOptions={[25, 50, 100]}
    />
  );

  const truncationNote = usersTruncated ? (
    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
      Showing the busiest users only — the rollup hit its server-side cap.
    </Typography>
  ) : null;

  if (isMobile) {
    return (
      <Box>
        {visible.length === 0 ? (
          <Typography color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
            No one has submitted a board yet.
          </Typography>
        ) : (
          <Stack divider={<Box sx={{ borderBottom: 1, borderColor: 'divider' }} />}>
            {visible.map((row) => (
              <Box key={row.userId} sx={{ p: 1.5 }}>
                <Typography variant="body2" sx={{ fontWeight: 500, overflowWrap: 'anywhere' }}>
                  {userLabel(row)}
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block">
                  {formatDay(row.firstAttemptAt)} → {formatDay(row.lastAttemptAt)}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {row.attempts.toLocaleString()} attempts · {row.added.toLocaleString()} added ·{' '}
                  {row.refused.toLocaleString()} refused · {row.stuck.toLocaleString()} stuck ·{' '}
                  {row.alreadyPublic.toLocaleString()} linked
                </Typography>
                <Typography variant="body2" sx={{ mt: 0.25 }}>
                  Owns now <strong>{row.ownsNow.toLocaleString()}</strong>
                </Typography>
              </Box>
            ))}
          </Stack>
        )}
        {pager}
        {truncationNote}
      </Box>
    );
  }

  return (
    <Box>
      <TableContainer sx={TABLE_SCROLL_SX}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>User</TableCell>
              <TableCell align="right">Attempts</TableCell>
              <TableCell align="right">Added</TableCell>
              <TableCell align="right">Refused</TableCell>
              <TableCell align="right">Stuck</TableCell>
              <TableCell align="right">Linked</TableCell>
              <TableCell align="right">Owns now</TableCell>
              <TableCell>First → last</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {visible.map((row) => (
              <TableRow key={row.userId} hover>
                <TableCell>
                  <Typography variant="body2" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>
                    {userLabel(row)}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ fontFamily: 'monospace' }}
                  >
                    {row.userId}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {row.attempts.toLocaleString()}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <CountCell value={row.added} color="success" variant="outlined" />
                </TableCell>
                <TableCell align="right">
                  <CountCell value={row.refused} color="error" variant="filled" />
                </TableCell>
                <TableCell align="right">
                  <CountCell value={row.stuck} color="warning" variant="filled" />
                </TableCell>
                <TableCell align="right">
                  <CountCell value={row.alreadyPublic} color="info" variant="outlined" />
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {row.ownsNow.toLocaleString()}
                  </Typography>
                </TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap', color: 'text.secondary' }}>
                  {formatDay(row.firstAttemptAt)} → {formatDay(row.lastAttemptAt)}
                </TableCell>
              </TableRow>
            ))}
            {visible.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}>
                  No one has submitted a board yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
      {pager}
      {truncationNote}
    </Box>
  );
}
