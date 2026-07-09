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
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import {
  useListEnrichmentNeedsHumanQuery,
  useReenrichEnrichmentJobMutation,
  type EnrichmentNeedsHumanRow,
} from '../../../features/admin/adminApi';
import { useGetFacetsQuery } from '../../../features/jobs/jobsApi';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS, FACET_LABELS } from '../../../constants/enrichment';
import { FacetSelect } from '../../../components/shared/filters/FacetSelect';
import { LoadingState } from '../../../components/shared/LoadingIndicator';
import { ErrorState } from '../../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../../lib/errors';
import { TABLE_SCROLL_SX } from '../../../config/responsive';
import { format } from 'date-fns';
import { CorrectionDialog } from './CorrectionDialog';

function facetChip(slug: string | null) {
  if (!slug) {
    return <Chip size="small" variant="outlined" label="—" sx={{ opacity: 0.5 }} />;
  }
  return <Chip size="small" variant="filled" label={FACET_LABELS[slug] ?? slug} />;
}

/**
 * The triage queue: judge-flagged rows on OPEN jobs, newest first, with the
 * agent's proposal + evidence one expand away and the two human actions
 * (Correct, Re-enrich) inline. Self-contained: owns its query, filters and
 * pagination (ProblemJobsTable pattern).
 */
export function NeedsHumanTable() {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [company, setCompany] = useState('');
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [level, setLevel] = useState<string | undefined>(undefined);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<EnrichmentNeedsHumanRow | null>(null);

  const { data: facets } = useGetFacetsQuery();
  const { data, isLoading, error, refetch } = useListEnrichmentNeedsHumanQuery({
    limit: rowsPerPage,
    offset: page * rowsPerPage,
    company: company.trim() || undefined,
    category,
    level,
  });
  const [reenrich, { isLoading: reenriching }] = useReenrichEnrichmentJobMutation();

  const rowKey = (row: EnrichmentNeedsHumanRow) => `${row.sourceId}:${row.jobListingId}`;

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
        <TextField
          size="small"
          label="Company"
          value={company}
          onChange={(e) => {
            setCompany(e.target.value);
            setPage(0);
          }}
          sx={{ minWidth: 170 }}
        />
        <FacetSelect
          label="Proposed category"
          options={facets?.categories ?? FALLBACK_CATEGORIES}
          value={category}
          onChange={(slug) => {
            setCategory(slug);
            setPage(0);
          }}
        />
        <FacetSelect
          label="Proposed level"
          options={facets?.levels ?? FALLBACK_LEVELS}
          value={level}
          onChange={(slug) => {
            setLevel(slug);
            setPage(0);
          }}
        />
      </Box>

      {error ? (
        <ErrorState
          inline
          message={extractErrorMessage(error, 'Failed to load the needs-human queue')}
          onRetry={() => refetch()}
        />
      ) : isLoading || !data ? (
        <LoadingState minHeight={160} caption="Loading queue…" />
      ) : data.rows.length === 0 ? (
        <Typography color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
          Queue is clear — no rows need a human.
        </Typography>
      ) : (
        <>
          <Box sx={TABLE_SCROLL_SX}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell width={36} />
                  <TableCell>Job</TableCell>
                  <TableCell>Proposed</TableCell>
                  <TableCell align="right">Confidence</TableCell>
                  <TableCell align="right">Enriched</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.rows.map((row) => {
                  const key = rowKey(row);
                  const isOpen = expanded === key;
                  return (
                    <Fragment key={key}>
                      <TableRow hover>
                        <TableCell padding="none">
                          <IconButton
                            size="small"
                            aria-label={isOpen ? 'Collapse details' : 'Expand details'}
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
                            {facetChip(row.category)}
                            {facetChip(row.level)}
                          </Box>
                        </TableCell>
                        <TableCell align="right">
                          {row.classifyConfidence != null
                            ? row.classifyConfidence.toFixed(2)
                            : '—'}
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
                        <TableCell colSpan={6} sx={{ py: 0, border: isOpen ? undefined : 0 }}>
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
                              {row.tags.length > 0 && (
                                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 0.5 }}>
                                  {row.tags.map((tag) => (
                                    <Chip key={tag} size="small" variant="outlined" label={tag} />
                                  ))}
                                </Box>
                              )}
                              {row.cleanDescription && (
                                <Typography
                                  variant="caption"
                                  color="text.secondary"
                                  sx={{
                                    display: '-webkit-box',
                                    WebkitLineClamp: 4,
                                    WebkitBoxOrient: 'vertical',
                                    overflow: 'hidden',
                                  }}
                                >
                                  {row.cleanDescription}
                                </Typography>
                              )}
                              <Typography variant="caption" color="text.secondary" display="block">
                                taxonomy {row.taxonomyVersion ?? '—'} · judged{' '}
                                {row.judged ? 'yes' : 'no'}
                                {row.judgePassed != null &&
                                  ` · passed ${row.judgePassed ? 'yes' : 'no'}`}
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
          </Box>
          <TablePagination
            component="div"
            count={data.total}
            page={page}
            onPageChange={(_e, newPage) => setPage(newPage)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(e) => {
              setRowsPerPage(parseInt(e.target.value, 10));
              setPage(0);
            }}
            rowsPerPageOptions={[10, 25, 50]}
          />
        </>
      )}

      <CorrectionDialog
        open={correcting !== null}
        row={correcting}
        onClose={() => setCorrecting(null)}
      />
    </Box>
  );
}
