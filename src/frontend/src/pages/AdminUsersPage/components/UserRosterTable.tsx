import { useMemo, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
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

const PROVIDER_LABEL: Record<string, string> = {
  google: 'Google',
  email: 'Email',
  other: 'Other',
};

function formatJoined(iso: string): string {
  if (!iso) return '—';
  const idx = iso.indexOf('T');
  return idx > 0 ? iso.slice(0, idx) : iso;
}

export function UserRosterTable({ users }: UserRosterTableProps) {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [search, setSearch] = useState('');
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
    if (!search.trim()) return users;
    const q = search.trim().toLowerCase();
    return users.filter(
      (u) =>
        u.email.toLowerCase().includes(q) ||
        (u.displayName?.toLowerCase().includes(q) ?? false)
    );
  }, [users, search]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      const cmp = a.createdAt.localeCompare(b.createdAt);
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [filtered, sortDir]);

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
      setActionError(
        extractErrorMessage(err, `Failed to grant admin to ${target.email}`)
      );
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
      setActionError(
        extractErrorMessage(err, `Failed to revoke admin from ${target.email}`)
      );
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
            {filtered.length.toLocaleString()}{' '}
            {filtered.length === 1 ? 'user' : 'users'}
          </Typography>
        </Box>
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

      {actionError && (
        <Alert
          severity="error"
          onClose={() => setActionError(null)}
          sx={{ mx: 2, mb: 2 }}
        >
          {actionError}
        </Alert>
      )}

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Email</TableCell>
              <TableCell>Name</TableCell>
              <TableCell align="right" sortDirection={sortDir}>
                <TableSortLabel
                  active
                  direction={sortDir}
                  onClick={() => setSortDir(sortDir === 'asc' ? 'desc' : 'asc')}
                >
                  Joined
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
                  <TableCell sx={{ color: 'text.secondary' }}>
                    {u.displayName ?? '—'}
                  </TableCell>
                  <TableCell align="right" sx={{ color: 'text.secondary' }}>
                    {formatJoined(u.createdAt)}
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={PROVIDER_LABEL[u.signupProvider] ?? 'Other'}
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
                <TableCell
                  colSpan={6}
                  sx={{ py: 4, textAlign: 'center', color: 'text.secondary' }}
                >
                  No matching users.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Menu
        anchorEl={menuAnchor}
        open={Boolean(menuAnchor)}
        onClose={handleMenuClose}
      >
        <MenuItem
          onClick={handleGrant}
          disabled={!menuRow || menuRow.isAdmin}
        >
          Make admin
        </MenuItem>
        <MenuItem
          onClick={handleRevoke}
          disabled={
            !menuRow || !menuRow.isAdmin || (menuRow ? isSelf(menuRow) : false)
          }
        >
          Revoke admin
          {menuRow && isSelf(menuRow) && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ ml: 1 }}
            >
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
