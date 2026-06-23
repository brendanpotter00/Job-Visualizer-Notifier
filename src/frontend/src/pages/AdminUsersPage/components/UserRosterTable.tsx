import { useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import FormControlLabel from '@mui/material/FormControlLabel';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import TableSortLabel from '@mui/material/TableSortLabel';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import SearchIcon from '@mui/icons-material/Search';
import {
  PROVIDER_LABEL,
  useGrantAdminMutation,
  useRevokeAdminMutation,
  type AdminUserRow,
} from '../../../features/admin/adminApi';
import { useCurrentUser } from '../../../features/auth/useCurrentUser';
import { extractErrorMessage } from '../../../lib/errors';

interface UserRosterTableProps {
  users: AdminUserRow[];
}

type SortDir = 'asc' | 'desc';
type SortField = 'createdAt' | 'visitCount' | 'lastVisitAt';

function formatJoined(iso: string): string {
  if (!iso) return '—';
  const idx = iso.indexOf('T');
  return idx > 0 ? iso.slice(0, idx) : iso;
}

export function UserRosterTable({ users }: UserRosterTableProps) {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [search, setSearch] = useState('');
  const [adminsOnly, setAdminsOnly] = useState(false);
  // Default sort stays newest-joined first (createdAt desc) — unchanged
  // behavior. Visits / Last active are opt-in via their column headers.
  const [sortField, setSortField] = useState<SortField>('createdAt');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);
  const [menuRow, setMenuRow] = useState<AdminUserRow | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { user: currentUser } = useCurrentUser();
  const [grantAdmin, grantState] = useGrantAdminMutation();
  const [revokeAdmin, revokeState] = useRevokeAdminMutation();

  const busyUserId =
    (grantState.isLoading && (grantState.originalArgs?.userId ?? null)) ||
    (revokeState.isLoading && (revokeState.originalArgs?.userId ?? null)) ||
    null;

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!adminsOnly && !q) return users;
    return users.filter((u) => {
      if (adminsOnly && !u.isAdmin) return false;
      if (!q) return true;
      return (
        u.email.toLowerCase().includes(q) || (u.displayName?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [users, search, adminsOnly]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      let cmp: number;
      switch (sortField) {
        case 'visitCount':
          cmp = (a.visitCount ?? 0) - (b.visitCount ?? 0);
          break;
        case 'lastVisitAt':
          // Null last_visit_at (never visited) sorts to the bottom on desc.
          cmp = (a.lastVisitAt ?? '').localeCompare(b.lastVisitAt ?? '');
          break;
        case 'createdAt':
        default:
          cmp = a.createdAt.localeCompare(b.createdAt);
          break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [filtered, sortField, sortDir]);

  // Click a column header: toggle direction if it's already the active sort
  // field, else switch to it defaulting to descending (newest / most first).
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('desc');
    }
  };

  const sliced = useMemo(() => {
    const start = page * rowsPerPage;
    return sorted.slice(start, start + rowsPerPage);
  }, [sorted, page, rowsPerPage]);

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>, row: AdminUserRow) => {
    setMenuAnchor(event.currentTarget);
    setMenuRow(row);
  };

  const handleMenuClose = () => {
    setMenuAnchor(null);
    setMenuRow(null);
  };

  const handleGrant = async () => {
    if (!menuRow) return;
    const target = menuRow;
    handleMenuClose();
    setActionError(null);
    try {
      await grantAdmin({ userId: target.id }).unwrap();
    } catch (err) {
      setActionError(extractErrorMessage(err, `Failed to grant admin to ${target.email}`));
    }
  };

  const handleRevoke = async () => {
    if (!menuRow) return;
    const target = menuRow;
    handleMenuClose();
    setActionError(null);
    try {
      await revokeAdmin({ userId: target.id }).unwrap();
    } catch (err) {
      setActionError(extractErrorMessage(err, `Failed to revoke admin from ${target.email}`));
    }
  };

  const isSelf = (row: AdminUserRow) => currentUser?.id === row.id;

  return (
    <Paper variant="outlined">
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 2,
          p: 2,
        }}
      >
        <Box>
          <Typography variant="h6" component="h2">
            User roster
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {filtered.length.toLocaleString()} {filtered.length === 1 ? 'user' : 'users'}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={adminsOnly}
                onChange={(e) => {
                  setAdminsOnly(e.target.checked);
                  setPage(0);
                }}
              />
            }
            label="Admins only"
          />
          <TextField
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            placeholder="Search email or name"
            size="small"
            variant="outlined"
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" color="action" />
                  </InputAdornment>
                ),
              },
            }}
            sx={{ width: { xs: 200, sm: 280 } }}
          />
        </Box>
      </Box>

      {actionError && (
        <Alert severity="error" onClose={() => setActionError(null)} sx={{ mx: 2, mb: 2 }}>
          {actionError}
        </Alert>
      )}

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Email</TableCell>
              <TableCell>Name</TableCell>
              <TableCell align="right" sortDirection={sortField === 'createdAt' ? sortDir : false}>
                <TableSortLabel
                  active={sortField === 'createdAt'}
                  direction={sortField === 'createdAt' ? sortDir : 'asc'}
                  onClick={() => handleSort('createdAt')}
                >
                  Joined
                </TableSortLabel>
              </TableCell>
              <TableCell align="right" sortDirection={sortField === 'visitCount' ? sortDir : false}>
                <TableSortLabel
                  active={sortField === 'visitCount'}
                  direction={sortField === 'visitCount' ? sortDir : 'asc'}
                  onClick={() => handleSort('visitCount')}
                >
                  Visits
                </TableSortLabel>
              </TableCell>
              <TableCell
                align="right"
                sortDirection={sortField === 'lastVisitAt' ? sortDir : false}
              >
                <TableSortLabel
                  active={sortField === 'lastVisitAt'}
                  direction={sortField === 'lastVisitAt' ? sortDir : 'asc'}
                  onClick={() => handleSort('lastVisitAt')}
                >
                  Last active
                </TableSortLabel>
              </TableCell>
              <TableCell>Provider</TableCell>
              <TableCell align="center">Admin</TableCell>
              <TableCell align="right" sx={{ width: 56 }}>
                {/* Actions */}
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sliced.map((u) => {
              const isBusy = busyUserId === u.id;
              return (
                <TableRow key={u.id} hover>
                  <TableCell>{u.email}</TableCell>
                  <TableCell sx={{ color: 'text.secondary' }}>{u.displayName ?? '—'}</TableCell>
                  <TableCell align="right" sx={{ color: 'text.secondary' }}>
                    {formatJoined(u.createdAt)}
                  </TableCell>
                  <TableCell align="right">{u.visitCount.toLocaleString()}</TableCell>
                  <TableCell align="right" sx={{ color: 'text.secondary' }}>
                    {formatJoined(u.lastVisitAt ?? '')}
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={PROVIDER_LABEL[u.signupProvider]}
                      size="small"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell align="center">
                    {u.isAdmin ? (
                      <Chip label="Admin" size="small" color="primary" />
                    ) : (
                      <Typography component="span" color="text.disabled">
                        —
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {isBusy ? (
                      <CircularProgress size={18} />
                    ) : (
                      <IconButton
                        aria-label={`Actions for ${u.email}`}
                        size="small"
                        onClick={(e) => handleMenuOpen(e, u)}
                      >
                        <MoreVertIcon fontSize="small" />
                      </IconButton>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {sliced.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}>
                  No matching users.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={handleMenuClose}>
        <MenuItem onClick={handleGrant} disabled={!menuRow || menuRow.isAdmin}>
          Make admin
        </MenuItem>
        <MenuItem
          onClick={handleRevoke}
          disabled={!menuRow || !menuRow.isAdmin || (menuRow ? isSelf(menuRow) : false)}
        >
          Revoke admin
          {menuRow && isSelf(menuRow) && (
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              (you)
            </Typography>
          )}
        </MenuItem>
      </Menu>

      <TablePagination
        component="div"
        count={filtered.length}
        page={page}
        onPageChange={(_, p) => setPage(p)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(e) => {
          setRowsPerPage(parseInt(e.target.value, 10));
          setPage(0);
        }}
        rowsPerPageOptions={[25, 50, 100]}
      />
    </Paper>
  );
}
