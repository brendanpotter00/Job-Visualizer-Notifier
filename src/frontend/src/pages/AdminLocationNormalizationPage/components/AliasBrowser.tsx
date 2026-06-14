import { Fragment, useMemo, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import Tabs from '@mui/material/Tabs';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import SearchIcon from '@mui/icons-material/Search';
import {
  useGetAliasOriginalsQuery,
  useListLocationAliasesQuery,
  useReverseSearchLocationsQuery,
  type AliasRow,
  type CanonicalLocation,
  type ReverseLocation,
  type ReverseResult,
} from '../../../features/admin/adminApi';
import { LoadingState } from '../../../components/shared/LoadingIndicator';
import { ErrorState } from '../../../components/shared/ErrorDisplay';
import { EmptyState } from '../../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../../lib/errors';
import { useDebouncedValue } from '../../../hooks/useDebouncedValue';

interface AliasBrowserProps {
  onEdit: (alias: AliasRow) => void;
}

type BrowserMode = 'forward' | 'reverse';

const FORWARD_PAGE_SIZE = 25;
const REVERSE_LIMIT = 50;
const REVERSE_RAWTEXT_VISIBLE = 5;

function locationChipLabel(loc: CanonicalLocation | ReverseLocation): string {
  return loc.canonicalName;
}

export function AliasBrowser({ onEdit }: AliasBrowserProps) {
  const [mode, setMode] = useState<BrowserMode>('forward');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [expandedRawText, setExpandedRawText] = useState<string | null>(null);

  const debouncedSearch = useDebouncedValue(search, 300);
  const contains = debouncedSearch.trim();

  // Reset pagination and any open expansion whenever the (debounced) search
  // term or the active tab changes. We track the last-seen key and adjust
  // state *during render* — React's documented alternative to a reset effect
  // (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes).
  // The debounced ``contains`` can't be reset in the input's onChange, so the
  // previous-value comparison is the clean way to follow it.
  const resetKey = `${mode}:${contains}`;
  const [lastResetKey, setLastResetKey] = useState(resetKey);
  if (resetKey !== lastResetKey) {
    setLastResetKey(resetKey);
    setPage(0);
    setExpandedRawText(null);
  }

  const offset = page * FORWARD_PAGE_SIZE;

  const forwardQuery = useListLocationAliasesQuery(
    { contains, limit: FORWARD_PAGE_SIZE, offset },
    { skip: mode !== 'forward' }
  );
  const reverseQuery = useReverseSearchLocationsQuery(
    { contains, limit: REVERSE_LIMIT },
    { skip: mode !== 'reverse' }
  );

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 2,
          mb: 2,
        }}
      >
        <Tabs
          value={mode}
          onChange={(_, value: BrowserMode) => setMode(value)}
          aria-label="Alias browser direction"
        >
          <Tab value="forward" label="Alias → canonical" />
          <Tab value="reverse" label="Canonical → aliases" />
        </Tabs>
        <TextField
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={mode === 'forward' ? 'Search raw text' : 'Search canonical name'}
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

      {mode === 'forward' ? (
        <ForwardTable
          query={forwardQuery}
          page={page}
          onPageChange={setPage}
          expandedRawText={expandedRawText}
          onToggleExpand={(rawText) =>
            setExpandedRawText((prev) => (prev === rawText ? null : rawText))
          }
          onEdit={onEdit}
        />
      ) : (
        <ReverseTable query={reverseQuery} />
      )}
    </Box>
  );
}

// ─── Forward table ───────────────────────────────────────────────────────────

interface ForwardTableProps {
  query: ReturnType<typeof useListLocationAliasesQuery>;
  page: number;
  onPageChange: (page: number) => void;
  expandedRawText: string | null;
  onToggleExpand: (rawText: string) => void;
  onEdit: (alias: AliasRow) => void;
}

function ForwardTable({
  query,
  page,
  onPageChange,
  expandedRawText,
  onToggleExpand,
  onEdit,
}: ForwardTableProps) {
  const aliases = useMemo<AliasRow[]>(() => query.data?.aliases ?? [], [query.data]);
  const total = query.data?.total ?? 0;

  if (query.isLoading && !query.data) {
    return <LoadingState minHeight={160} caption="Loading aliases…" />;
  }
  if (query.error && !query.data) {
    return (
      <ErrorState
        inline
        message={extractErrorMessage(query.error, 'Failed to load aliases')}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (aliases.length === 0) {
    return <EmptyState title="No aliases" message="No alias mappings match this search." />;
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Raw text</TableCell>
            <TableCell>Source</TableCell>
            <TableCell align="right">Confidence</TableCell>
            <TableCell>Canonical</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {aliases.map((alias) => {
            const isExpanded = expandedRawText === alias.rawText;
            return (
              <Fragment key={alias.rawText}>
                <TableRow hover>
                  <TableCell sx={{ fontFamily: 'monospace' }}>{alias.rawText}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={alias.source}
                      color={alias.source === 'manual' ? 'primary' : 'default'}
                      variant={alias.source === 'manual' ? 'filled' : 'outlined'}
                    />
                  </TableCell>
                  <TableCell align="right">
                    {alias.confidence !== null ? alias.confidence.toFixed(2) : '—'}
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                      {alias.locations.map((loc) => (
                        <Chip
                          key={loc.id}
                          size="small"
                          variant="outlined"
                          label={locationChipLabel(loc)}
                        />
                      ))}
                      {alias.locations.length === 0 && (
                        <Typography variant="body2" color="text.disabled">
                          —
                        </Typography>
                      )}
                    </Stack>
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={0.5} sx={{ justifyContent: 'flex-end' }}>
                      <IconButton
                        size="small"
                        aria-label={
                          isExpanded
                            ? `Collapse originals for ${alias.rawText}`
                            : `Expand originals for ${alias.rawText}`
                        }
                        onClick={() => onToggleExpand(alias.rawText)}
                      >
                        {isExpanded ? (
                          <KeyboardArrowUpIcon fontSize="small" />
                        ) : (
                          <KeyboardArrowDownIcon fontSize="small" />
                        )}
                      </IconButton>
                      <Button size="small" onClick={() => onEdit(alias)}>
                        Edit
                      </Button>
                    </Stack>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell colSpan={5} sx={{ py: 0, borderBottom: isExpanded ? undefined : 'none' }}>
                    <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                      <AliasOriginals rawText={alias.rawText} />
                    </Collapse>
                  </TableCell>
                </TableRow>
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
      <TablePagination
        component="div"
        count={total}
        page={page}
        onPageChange={(_, newPage) => onPageChange(newPage)}
        rowsPerPage={FORWARD_PAGE_SIZE}
        rowsPerPageOptions={[FORWARD_PAGE_SIZE]}
      />
    </TableContainer>
  );
}

// ─── Expanded originals ──────────────────────────────────────────────────────

function AliasOriginals({ rawText }: { rawText: string }) {
  const { data, isLoading, error, refetch } = useGetAliasOriginalsQuery({ rawText, limit: 50 });

  if (isLoading && !data) {
    return <LoadingState minHeight={80} caption="Loading original strings…" />;
  }
  if (error && !data) {
    return (
      <Box sx={{ py: 2 }}>
        <ErrorState
          inline
          message={extractErrorMessage(error, 'Failed to load original strings')}
          onRetry={() => refetch()}
        />
      </Box>
    );
  }

  const originals = data?.originals ?? [];

  return (
    <Box sx={{ py: 2, pl: 2 }}>
      <Typography variant="subtitle2" gutterBottom>
        Original job location strings that normalize to this key
      </Typography>
      {originals.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No original strings recorded.
        </Typography>
      ) : (
        <Stack spacing={0.5}>
          {originals.map((orig) => (
            <Box
              key={orig.original}
              sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}
            >
              <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                {orig.original}
              </Typography>
              <Chip
                size="small"
                variant="outlined"
                label={`${orig.jobIds.length} ${orig.jobIds.length === 1 ? 'job' : 'jobs'}`}
              />
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}

// ─── Reverse table ───────────────────────────────────────────────────────────

interface ReverseTableProps {
  query: ReturnType<typeof useReverseSearchLocationsQuery>;
}

function ReverseTable({ query }: ReverseTableProps) {
  const results = useMemo<ReverseResult[]>(() => query.data?.results ?? [], [query.data]);

  if (query.isLoading && !query.data) {
    return <LoadingState minHeight={160} caption="Loading canonical locations…" />;
  }
  if (query.error && !query.data) {
    return (
      <ErrorState
        inline
        message={extractErrorMessage(query.error, 'Failed to load canonical locations')}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (results.length === 0) {
    return (
      <EmptyState title="No canonical locations" message="No canonical locations match this search." />
    );
  }

  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Canonical</TableCell>
            <TableCell>Kind</TableCell>
            <TableCell>Raw texts</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {results.map((result) => {
            const visible = result.rawTexts.slice(0, REVERSE_RAWTEXT_VISIBLE);
            const overflow = result.rawTexts.length - visible.length;
            return (
              <TableRow key={result.location.id} hover>
                <TableCell>
                  <Chip size="small" variant="outlined" label={result.location.canonicalName} />
                </TableCell>
                <TableCell sx={{ color: 'text.secondary' }}>{result.location.kind}</TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                    {visible.map((raw) => (
                      <Chip
                        key={raw}
                        size="small"
                        variant="outlined"
                        label={raw}
                        sx={{ fontFamily: 'monospace' }}
                      />
                    ))}
                    {overflow > 0 && (
                      <Chip size="small" label={`+${overflow} more`} color="default" />
                    )}
                    {result.rawTexts.length === 0 && (
                      <Typography variant="body2" color="text.disabled">
                        —
                      </Typography>
                    )}
                  </Stack>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
