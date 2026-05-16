import { useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import InputAdornment from '@mui/material/InputAdornment';
import SearchIcon from '@mui/icons-material/Search';
import type { AdminUserRow } from '../../../features/admin/adminApi';
import { OPS, SX } from '../adminUsersTheme';

interface UserRosterTableProps {
  users: AdminUserRow[];
}

function formatJoined(iso: string): string {
  // Stored as ISO-8601 Text. Render as YYYY-MM-DD (chronologically sortable
  // and reads naturally in a monospace column).
  if (!iso) return '—';
  const idx = iso.indexOf('T');
  return idx > 0 ? iso.slice(0, idx) : iso;
}

const PROVIDER_BADGE: Record<string, { label: string; color: string }> = {
  google: { label: 'GOOGLE', color: '#60a5fa' },
  email: { label: 'EMAIL', color: '#fbbf24' },
  other: { label: 'OTHER', color: '#94a3b8' },
};

const COL_STYLE = {
  fontFamily: OPS.mono,
  fontSize: 13,
  color: OPS.textPrimary,
  borderBottom: `1px solid ${OPS.border}`,
  py: 1.25,
};

const HEAD_STYLE = {
  ...SX.caption,
  borderBottom: `1px solid ${OPS.borderStrong}`,
  py: 1.25,
};

export function UserRosterTable({ users }: UserRosterTableProps) {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search.trim()) return users;
    const q = search.trim().toLowerCase();
    return users.filter(
      (u) =>
        u.email.toLowerCase().includes(q) ||
        (u.displayName?.toLowerCase().includes(q) ?? false)
    );
  }, [users, search]);

  const sliced = useMemo(() => {
    const start = page * rowsPerPage;
    return filtered.slice(start, start + rowsPerPage);
  }, [filtered, page, rowsPerPage]);

  return (
    <Box sx={SX.surface}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 2,
          px: 2.5,
          py: 2,
          borderBottom: `1px solid ${OPS.border}`,
        }}
      >
        <Box sx={SX.caption}>USER ROSTER · {filtered.length} ROWS</Box>
        <TextField
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
          placeholder="filter email or name"
          size="small"
          variant="outlined"
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon sx={{ color: OPS.textDim, fontSize: 18 }} />
              </InputAdornment>
            ),
          }}
          sx={{
            width: { xs: 180, sm: 260 },
            '& .MuiOutlinedInput-root': {
              fontFamily: OPS.mono,
              fontSize: 13,
              color: OPS.textPrimary,
              bgcolor: OPS.surfaceAlt,
              borderRadius: 0,
              '& fieldset': { borderColor: OPS.border },
              '&:hover fieldset': { borderColor: OPS.borderStrong },
              '&.Mui-focused fieldset': { borderColor: OPS.accent },
            },
            '& .MuiInputBase-input::placeholder': {
              color: OPS.textDim,
              opacity: 1,
            },
          }}
        />
      </Box>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={HEAD_STYLE}>EMAIL</TableCell>
              <TableCell sx={HEAD_STYLE}>NAME</TableCell>
              <TableCell sx={HEAD_STYLE} align="right">
                JOINED
              </TableCell>
              <TableCell sx={HEAD_STYLE}>PROVIDER</TableCell>
              <TableCell sx={HEAD_STYLE} align="center">
                ADMIN
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sliced.map((u, i) => {
              const badge = PROVIDER_BADGE[u.signupProvider] ?? PROVIDER_BADGE.other;
              return (
                <TableRow
                  key={u.id}
                  sx={{
                    bgcolor: i % 2 === 0 ? 'transparent' : OPS.surfaceAlt,
                    '&:hover': { bgcolor: '#16203a' },
                  }}
                >
                  <TableCell sx={COL_STYLE}>{u.email}</TableCell>
                  <TableCell sx={{ ...COL_STYLE, color: OPS.textMuted }}>
                    {u.displayName ?? '—'}
                  </TableCell>
                  <TableCell sx={{ ...COL_STYLE, color: OPS.textMuted }} align="right">
                    {formatJoined(u.createdAt)}
                  </TableCell>
                  <TableCell sx={COL_STYLE}>
                    <Box
                      component="span"
                      sx={{
                        display: 'inline-block',
                        px: 1,
                        py: 0.25,
                        fontSize: 10.5,
                        letterSpacing: '0.12em',
                        fontWeight: 700,
                        color: badge.color,
                        border: `1px solid ${badge.color}55`,
                        bgcolor: `${badge.color}11`,
                      }}
                    >
                      {badge.label}
                    </Box>
                  </TableCell>
                  <TableCell sx={COL_STYLE} align="center">
                    {u.isAdmin ? (
                      <Box
                        component="span"
                        sx={{
                          display: 'inline-block',
                          px: 1,
                          py: 0.25,
                          fontSize: 10.5,
                          letterSpacing: '0.16em',
                          fontWeight: 700,
                          color: OPS.adminBadge,
                          border: `1px solid ${OPS.adminBadge}55`,
                          bgcolor: `${OPS.adminBadge}11`,
                        }}
                      >
                        ADMIN
                      </Box>
                    ) : (
                      <Box component="span" sx={{ color: OPS.textDim }}>
                        ·
                      </Box>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {sliced.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} sx={{ ...COL_STYLE, color: OPS.textMuted, py: 4, textAlign: 'center' }}>
                  No matching users.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

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
        sx={{
          color: OPS.textMuted,
          borderTop: `1px solid ${OPS.border}`,
          fontFamily: OPS.mono,
          '& .MuiTablePagination-selectLabel, & .MuiTablePagination-displayedRows': {
            fontFamily: OPS.mono,
            fontSize: 12,
            color: OPS.textMuted,
          },
          '& .MuiTablePagination-select': {
            fontFamily: OPS.mono,
            color: OPS.textPrimary,
          },
          '& .MuiSvgIcon-root': { color: OPS.textMuted },
        }}
      />
    </Box>
  );
}
