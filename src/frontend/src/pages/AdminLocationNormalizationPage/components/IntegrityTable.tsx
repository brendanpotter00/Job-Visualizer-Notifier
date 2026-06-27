import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import type { IntegrityCheck } from '../../../features/admin/adminApi';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { integritySeverityToMuiColor } from '../verdict';

interface IntegrityTableProps {
  checks: IntegrityCheck[];
}

export function IntegrityTable({ checks }: IntegrityTableProps) {
  // Bounded by contract (the runbook defines exactly 9 invariants), so no
  // pagination is needed — the table renders every check.
  const issueCount = checks.filter((c) => c.count > 0).length;
  const hasIssues = issueCount > 0;

  return (
    <Box>
      <Typography
        variant="subtitle2"
        sx={{ mb: 1.5 }}
        color={hasIssues ? 'error.main' : 'success.main'}
      >
        {hasIssues
          ? `⚠ ${issueCount} integrity ${issueCount === 1 ? 'issue' : 'issues'}`
          : 'All invariants clean'}
      </Typography>
      <TableContainer sx={TABLE_SCROLL_SX}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>ID</TableCell>
              <TableCell>Invariant</TableCell>
              <TableCell align="right">Count</TableCell>
              <TableCell align="center">Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {checks.map((check) => (
              <TableRow key={check.id} hover>
                <TableCell sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                  {check.id}
                </TableCell>
                <TableCell>{check.label}</TableCell>
                <TableCell align="right">{check.count.toLocaleString()}</TableCell>
                <TableCell align="center">
                  {check.count === 0 ? (
                    <CheckCircleIcon
                      color="success"
                      fontSize="small"
                      aria-label="clean"
                      sx={{ verticalAlign: 'middle' }}
                    />
                  ) : (
                    <Chip
                      size="small"
                      label={check.severity}
                      color={integritySeverityToMuiColor(check.severity)}
                    />
                  )}
                </TableCell>
              </TableRow>
            ))}
            {checks.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} align="center" sx={{ color: 'text.secondary', py: 3 }}>
                  No integrity checks reported.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}
