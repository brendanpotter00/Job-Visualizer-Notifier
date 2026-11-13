import { Fragment, useState } from 'react';
import Alert from '@mui/material/Alert';
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
import TableSortLabel from '@mui/material/TableSortLabel';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import {
  useListEnrichmentNeedsHumanQuery,
  useConfirmEnrichmentMutation,
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
import { JobDescriptionDialog } from './JobDescriptionDialog';

/** The four columns the backend's sort allowlist accepts. */
type SortKey =
  | 'enriched_at'
  | 'classify_confidence'
  | 'judge_confidence'
  | 'subcategory_confidence';

/**
 * Rendered through FacetSelect, so these are shaped like facet options. Values
 * mirror the backend's `_NEEDS_HUMAN_SUBCATEGORY_STATES` keys; 'any' is the
 * default and is sent as "no filter" rather than as a param.
 */
const SUBCATEGORY_STATE_OPTIONS = [
  { slug: 'unlabelled_swe', label: 'Unlabelled SWE', sortOrder: 0, parentSlug: null },
  { slug: 'labelled', label: 'Labelled', sortOrder: 1, parentSlug: null },
];

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
  const [subcategory, setSubcategory] = useState<string | undefined>(undefined);
  const [subcategoryState, setSubcategoryState] = useState<string | undefined>(undefined);
  const [sort, setSort] = useState<SortKey>('enriched_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<EnrichmentNeedsHumanRow | null>(null);
  const [viewingDescription, setViewingDescription] = useState<EnrichmentNeedsHumanRow | null>(
    null
  );
  const [reenrichError, setReenrichError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const { data: facets } = useGetFacetsQuery();
  const { data, isLoading, error, refetch } = useListEnrichmentNeedsHumanQuery({
    limit: rowsPerPage,
    offset: page * rowsPerPage,
    company: company.trim() || undefined,
    category,
    level,
    sort,
    sortDir,
    subcategory,
    subcategoryState,
  });
  const [reenrich, { isLoading: reenriching }] = useReenrichEnrichmentJobMutation();
  const [confirm, { isLoading: confirming }] = useConfirmEnrichmentMutation();

  const rowKey = (row: EnrichmentNeedsHumanRow) => `${row.sourceId}:${row.jobListingId}`;

  /**
   * Clicking a header sorts by it descending; clicking the SAME header flips
   * the direction. Every path resets the offset — sorting a paged list without
   * returning to page 0 shows an arbitrary slice of the NEW order, which reads
   * as data loss.
   */
  const handleSort = (key: SortKey) => {
    if (sort === key) {
      setSortDir((dir) => (dir === 'asc' ? 'desc' : 'asc'));
    } else {
      setSort(key);
      setSortDir('desc');
    }
    setPage(0);
  };

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
        <FacetSelect
          label="Proposed subcategory"
          options={facets?.subcategories ?? []}
          value={subcategory}
          onChange={(slug) => {
            setSubcategory(slug);
            setPage(0);
          }}
        />
        {/*
          "Unlabelled SWE" is the lens that surfaces HUMAN-LOCKED SWE rows — the
          ones an admin corrected before subcategories existed. They are
          invisible in every other view, and the backfill's per-field unlock is
          the only thing that can reach them.
        */}
        <FacetSelect
          label="Subcategory state"
          options={SUBCATEGORY_STATE_OPTIONS}
          value={subcategoryState}
          onChange={(slug) => {
            setSubcategoryState(slug);
            setPage(0);
          }}
        />
      </Box>

      {reenrichError && (
        <Alert severity="error" onClose={() => setReenrichError(null)} sx={{ mb: 2 }}>
          {reenrichError}
        </Alert>
      )}

      {confirmError && (
        <Alert severity="error" onClose={() => setConfirmError(null)} sx={{ mb: 2 }}>
          {confirmError}
        </Alert>
      )}

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
                  <TableCell align="right" sortDirection={sort === 'classify_confidence' ? sortDir : false}>
                    <TableSortLabel
                      active={sort === 'classify_confidence'}
                      direction={sort === 'classify_confidence' ? sortDir : 'desc'}
                      onClick={() => handleSort('classify_confidence')}
                    >
                      Confidence
                    </TableSortLabel>
                  </TableCell>
                  <TableCell align="right" sortDirection={sort === 'subcategory_confidence' ? sortDir : false}>
                    <TableSortLabel
                      active={sort === 'subcategory_confidence'}
                      direction={sort === 'subcategory_confidence' ? sortDir : 'desc'}
                      onClick={() => handleSort('subcategory_confidence')}
                    >
                      Sub conf.
                    </TableSortLabel>
                  </TableCell>
                  <TableCell align="right" sortDirection={sort === 'enriched_at' ? sortDir : false}>
                    <TableSortLabel
                      active={sort === 'enriched_at'}
                      direction={sort === 'enriched_at' ? sortDir : 'desc'}
                      onClick={() => handleSort('enriched_at')}
                    >
                      Enriched
                    </TableSortLabel>
                  </TableCell>
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
                            {/* Filled = primary (index 0), outlined = secondary,
                                so primacy reads at a glance. */}
                            {(row.subcategories ?? []).map((slug, index) => (
                              <Chip
                                key={slug}
                                size="small"
                                variant={index === 0 ? 'filled' : 'outlined'}
                                color={index === 0 ? 'primary' : 'default'}
                                label={FACET_LABELS[slug] ?? slug}
                              />
                            ))}
                          </Box>
                        </TableCell>
                        <TableCell align="right">
                          {row.classifyConfidence != null ? row.classifyConfidence.toFixed(2) : '—'}
                        </TableCell>
                        <TableCell align="right">
                          {row.subcategoryConfidence != null
                            ? row.subcategoryConfidence.toFixed(2)
                            : '—'}
                        </TableCell>
                        <TableCell align="right">
                          {row.enrichedAt ? format(new Date(row.enrichedAt), 'MMM d HH:mm') : '—'}
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip
                            title={
                              row.category == null
                                ? 'No proposed labels — use Correct to set them'
                                : ''
                            }
                          >
                            {/* span wrapper: a disabled MUI button swallows the
                                events the Tooltip needs to fire. */}
                            <span>
                              <Button
                                size="small"
                                color="success"
                                startIcon={<CheckCircleOutlineIcon />}
                                disabled={confirming || row.category == null}
                                onClick={async () => {
                                  // Mirror the Correct/Re-enrich flows: surface a
                                  // failed confirm instead of failing silently.
                                  setConfirmError(null);
                                  try {
                                    await confirm({
                                      sourceId: row.sourceId,
                                      jobListingId: row.jobListingId,
                                    }).unwrap();
                                  } catch (e) {
                                    setConfirmError(
                                      extractErrorMessage(e, 'Failed to confirm this row')
                                    );
                                  }
                                }}
                              >
                                Confirm
                              </Button>
                            </span>
                          </Tooltip>
                          <Button size="small" onClick={() => setCorrecting(row)}>
                            Correct
                          </Button>
                          <Button
                            size="small"
                            color="inherit"
                            disabled={reenriching}
                            onClick={async () => {
                              // Mirror the Correct flow: a failed re-enrich must
                              // be visible, not fire-and-forget. ``.unwrap()``
                              // rethrows the RTK Query error so we can surface it.
                              setReenrichError(null);
                              try {
                                await reenrich({
                                  sourceId: row.sourceId,
                                  jobListingId: row.jobListingId,
                                }).unwrap();
                              } catch (e) {
                                setReenrichError(
                                  extractErrorMessage(e, 'Failed to re-enrich this job')
                                );
                              }
                            }}
                          >
                            Re-enrich
                          </Button>
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        {/* ⚠ 7, not 6 — the head row gained the "Sub conf."
                            column in this same commit. A stale colSpan leaves
                            the expander short of the full width, which looks
                            like a rendering bug and is one. */}
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
                              {row.tags.length > 0 && (
                                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 0.5 }}>
                                  {row.tags.map((tag) => (
                                    <Chip key={tag} size="small" variant="outlined" label={tag} />
                                  ))}
                                </Box>
                              )}
                              {row.cleanDescription && (
                                <Box sx={{ mb: 0.5 }}>
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
                                  <Button size="small" onClick={() => setViewingDescription(row)}>
                                    View full description
                                  </Button>
                                </Box>
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

      <JobDescriptionDialog
        open={viewingDescription !== null}
        row={viewingDescription}
        onClose={() => setViewingDescription(null)}
      />
    </Box>
  );
}
