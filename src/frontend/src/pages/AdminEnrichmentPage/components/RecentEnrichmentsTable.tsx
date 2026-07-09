import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import { useGetEnrichmentRecentQuery } from '../../../features/admin/adminApi';
import { FACET_LABELS } from '../../../constants/enrichment';
import { LoadingState } from '../../../components/shared/LoadingIndicator';
import { ErrorState } from '../../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../../lib/errors';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { format } from 'date-fns';

/**
 * The last N enrichment writes — eyeball the agent's live output (labels,
 * confidence, judge outcome) without opening a SQL console. Capped server-side;
 * no pagination on purpose: this is a glance surface, the queue is the work
 * surface.
 */
export function RecentEnrichmentsTable() {
  const { data: rows, isLoading, error, refetch } = useGetEnrichmentRecentQuery({ limit: 25 });

  if (error) {
    return (
      <ErrorState
        inline
        message={extractErrorMessage(error, 'Failed to load recent enrichments')}
        onRetry={() => refetch()}
      />
    );
  }
  if (isLoading || !rows) {
    return <LoadingState minHeight={120} caption="Loading recent enrichments…" />;
  }
  if (rows.length === 0) {
    return (
      <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
        Nothing enriched yet.
      </Typography>
    );
  }

  return (
    <Box sx={TABLE_SCROLL_SX}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Job</TableCell>
            <TableCell>Labels</TableCell>
            <TableCell align="right">Confidence</TableCell>
            <TableCell>Outcome</TableCell>
            <TableCell align="right">Enriched</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${row.sourceId}:${row.jobListingId}`} hover>
              <TableCell>
                {row.title ?? row.jobListingId}
                <Typography variant="caption" color="text.secondary" display="block">
                  {row.company}
                </Typography>
              </TableCell>
              <TableCell>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                  {row.category && (
                    <Chip size="small" label={FACET_LABELS[row.category] ?? row.category} />
                  )}
                  {row.level && <Chip size="small" label={FACET_LABELS[row.level] ?? row.level} />}
                  {row.tags.slice(0, 3).map((tag) => (
                    <Chip key={tag} size="small" variant="outlined" label={tag} />
                  ))}
                  {row.tags.length > 3 && (
                    <Chip size="small" variant="outlined" label={`+${row.tags.length - 3}`} />
                  )}
                </Box>
              </TableCell>
              <TableCell align="right">
                {row.classifyConfidence != null ? row.classifyConfidence.toFixed(2) : '—'}
              </TableCell>
              <TableCell>
                {row.humanCorrectedAt ? (
                  <Chip size="small" color="info" variant="outlined" label="human-corrected" />
                ) : row.needsHuman ? (
                  <Chip size="small" color="warning" variant="outlined" label="needs human" />
                ) : (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={row.judged ? (row.judgePassed ? 'judge passed' : 'judge corrected') : 'unjudged'}
                  />
                )}
              </TableCell>
              <TableCell align="right">
                {row.enrichedAt ? format(new Date(row.enrichedAt), 'MMM d HH:mm') : '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}
