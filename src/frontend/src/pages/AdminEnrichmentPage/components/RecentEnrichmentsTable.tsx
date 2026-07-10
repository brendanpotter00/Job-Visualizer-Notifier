import { Fragment, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import IconButton from '@mui/material/IconButton';
import Link from '@mui/material/Link';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import {
  useGetEnrichmentRecentQuery,
  useReenrichEnrichmentJobMutation,
  type EnrichmentRecentRow,
} from '../../../features/admin/adminApi';
import { FACET_LABELS } from '../../../constants/enrichment';
import { LoadingState } from '../../../components/shared/LoadingIndicator';
import { ErrorState } from '../../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../../lib/errors';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { format } from 'date-fns';
import { CorrectionDialog } from './CorrectionDialog';

/**
 * The last N enrichment writes — eyeball the agent's live output (labels,
 * confidence, judge outcome) without opening a SQL console. Capped server-side;
 * no pagination on purpose: this is a glance surface, the queue is the work
 * surface. Each row expands to the agent's evidence (judge notes + classifier
 * reasoning), and carries the same Correct / Re-enrich actions as the queue —
 * any row an admin can see is a row they can fix.
 */
export function RecentEnrichmentsTable() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<EnrichmentRecentRow | null>(null);
  const { data: rows, isLoading, error, refetch } = useGetEnrichmentRecentQuery({ limit: 25 });
  const [reenrich, { isLoading: reenriching }] = useReenrichEnrichmentJobMutation();

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
            <TableCell width={36} />
            <TableCell>Job</TableCell>
            <TableCell>Labels</TableCell>
            <TableCell align="right">Confidence</TableCell>
            <TableCell>Outcome</TableCell>
            <TableCell align="right">Enriched</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const key = `${row.sourceId}:${row.jobListingId}`;
            const isOpen = expanded === key;
            return (
              <Fragment key={key}>
                <TableRow hover>
                  <TableCell padding="none">
                    <IconButton
                      size="small"
                      aria-label={isOpen ? 'Collapse reasoning' : 'Expand reasoning'}
                      onClick={() => setExpanded(isOpen ? null : key)}
                    >
                      {isOpen ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
                    </IconButton>
                  </TableCell>
                  <TableCell>
                    {row.url ? (
                      <Link href={row.url} target="_blank" rel="noopener noreferrer">
                        {row.title ?? row.jobListingId}
                      </Link>
                    ) : (
                      (row.title ?? row.jobListingId)
                    )}
                    <Typography variant="caption" color="text.secondary" display="block">
                      {row.company}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {row.category && (
                        <Chip size="small" label={FACET_LABELS[row.category] ?? row.category} />
                      )}
                      {row.level && (
                        <Chip size="small" label={FACET_LABELS[row.level] ?? row.level} />
                      )}
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
                        label={
                          row.judged ? (row.judgePassed ? 'judge passed' : 'judge corrected') : 'unjudged'
                        }
                      />
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {row.enrichedAt ? format(new Date(row.enrichedAt), 'MMM d HH:mm') : '—'}
                  </TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => setCorrecting(row)}>
                      Correct
                    </Button>
                    <Button
                      size="small"
                      color="inherit"
                      disabled={reenriching}
                      onClick={() =>
                        reenrich({ sourceId: row.sourceId, jobListingId: row.jobListingId })
                      }
                    >
                      Re-enrich
                    </Button>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell colSpan={7} sx={{ py: 0, border: isOpen ? undefined : 0 }}>
                    <Collapse in={isOpen} unmountOnExit>
                      <Box sx={{ py: 1.5, pl: 4 }}>
                        {row.judgeNotes && (
                          <Typography variant="body2" sx={{ mb: 0.5 }}>
                            <strong>Judge:</strong> {row.judgeNotes}
                            {row.judgeConfidence != null &&
                              ` (confidence ${row.judgeConfidence.toFixed(2)})`}
                          </Typography>
                        )}
                        {row.classifyReasoning && (
                          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                            <strong>Classifier:</strong> {row.classifyReasoning}
                          </Typography>
                        )}
                        {!row.judgeNotes && !row.classifyReasoning && (
                          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                            No reasoning recorded for this row.
                          </Typography>
                        )}
                        {row.tags.length > 3 && (
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 0.5 }}>
                            {row.tags.map((tag) => (
                              <Chip key={tag} size="small" variant="outlined" label={tag} />
                            ))}
                          </Box>
                        )}
                        <Typography variant="caption" color="text.secondary" display="block">
                          taxonomy {row.taxonomyVersion ?? '—'} · judged {row.judged ? 'yes' : 'no'}
                          {row.judgePassed != null && ` · passed ${row.judgePassed ? 'yes' : 'no'}`}
                        </Typography>
                      </Box>
                    </Collapse>
                  </TableCell>
                </TableRow>
              </Fragment>
            );
          })}
        </TableBody>
      </Table>

      <CorrectionDialog
        open={correcting !== null}
        row={correcting}
        onClose={() => setCorrecting(null)}
      />
    </Box>
  );
}
