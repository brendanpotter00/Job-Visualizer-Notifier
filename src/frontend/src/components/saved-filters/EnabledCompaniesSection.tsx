import { memo, useCallback, useState, useEffect, useMemo, type KeyboardEvent } from 'react';
import Accordion from '@mui/material/Accordion';
import AccordionSummary from '@mui/material/AccordionSummary';
import AccordionDetails from '@mui/material/AccordionDetails';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import FormControlLabel from '@mui/material/FormControlLabel';
import Paper from '@mui/material/Paper';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { COMPANIES } from '../../config/companies';
import { useEnabledCompanies } from '../../features/preferences/useEnabledCompanies';
import { CompanyLogo } from '../shared/CompanyLogo/CompanyLogo';
import { SectionSaveButton } from './SectionSaveButton';
import { LoadingState } from '../shared/LoadingIndicator';
import { extractErrorMessage } from '../../lib/errors';

/**
 * 'all'    — no stored list. The server treats an empty list as "every
 *            company", so companies added later show up on their own.
 * 'custom' — an explicit list, plus the auto-enroll flag for whether companies
 *            added later join it (the server only consults that flag when the
 *            list is non-empty).
 */
type CompanyMode = 'all' | 'custom';

interface CompanyOption {
  id: string;
  name: string;
}

const SORTED_COMPANIES: CompanyOption[] = COMPANIES.map((c) => ({ id: c.id, name: c.name })).sort(
  (a, b) => a.name.localeCompare(b.name)
);
const ALL_IDS = SORTED_COMPANIES.map((c) => c.id);

function canonical(ids: string[]): string[] {
  return [...new Set(ids)].sort();
}

interface CompanyChipProps {
  id: string;
  name: string;
  selected: boolean;
  onToggle: (id: string) => void;
}

/** Memoized so toggling one company re-renders one chip, not the whole grid. */
const CompanyChip = memo(function CompanyChip({ id, name, selected, onToggle }: CompanyChipProps) {
  return (
    <Chip
      label={name}
      // The span wrapper is what receives MUI's `MuiChip-icon` class (and its
      // margins); CompanyLogo has no className prop.
      icon={
        <Box component="span" sx={{ display: 'inline-flex' }}>
          <CompanyLogo companyId={id} displayName={name} size={18} decorative />
        </Box>
      }
      onClick={() => onToggle(id)}
      color={selected ? 'primary' : 'default'}
      variant={selected ? 'filled' : 'outlined'}
      size="small"
      clickable
      aria-pressed={selected}
      data-testid={`company-chip-${id}`}
    />
  );
});

/** Which companies feed the Recent Job Postings page. */
export function EnabledCompaniesSection() {
  const { ids, autoEnroll, loading, error, save } = useEnabledCompanies();

  const [mode, setMode] = useState<CompanyMode>('all');
  const [draftIds, setDraftIds] = useState<string[]>([]);
  const [draftAutoEnroll, setDraftAutoEnroll] = useState(true);
  const [filter, setFilter] = useState('');
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Re-seed the draft whenever the saved list (re)loads or a save lands. A
  // non-empty saved list is the only thing that puts the section in 'custom'.
  useEffect(() => {
    const saved = ids ?? [];
    setDraftIds(saved);
    setMode(saved.length > 0 ? 'custom' : 'all');
    setSaveError(null);
  }, [ids]);

  // Checked by default. The stored flag only means anything alongside a
  // non-empty list, so someone coming from "All companies" starts checked even
  // if a stale `false` is on their row.
  const savedAutoEnroll = (ids ?? []).length > 0 ? (autoEnroll ?? true) : true;
  useEffect(() => {
    setDraftAutoEnroll(savedAutoEnroll);
  }, [savedAutoEnroll]);

  // A newer slice-level error must not be shadowed by a stale save error.
  useEffect(() => {
    if (error) setSaveError(null);
  }, [error]);

  const draftSet = useMemo(() => new Set(draftIds), [draftIds]);
  const selectedCount = useMemo(
    () => SORTED_COMPANIES.filter((c) => draftSet.has(c.id)).length,
    [draftSet]
  );

  const query = filter.trim().toLowerCase();
  const visibleCompanies = useMemo(
    () =>
      query
        ? SORTED_COMPANIES.filter((c) => c.name.toLowerCase().includes(query))
        : SORTED_COMPANIES,
    [query]
  );

  // What Save would persist: "All companies" is stored as an empty list.
  const idsToSave = useMemo(() => (mode === 'all' ? [] : canonical(draftIds)), [mode, draftIds]);
  const idsDirty = idsToSave.join('|') !== canonical(ids ?? []).join('|');
  const autoEnrollDirty = mode === 'custom' && draftAutoEnroll !== savedAutoEnroll;
  const dirty = idsDirty || autoEnrollDirty;

  // Any edit clears stale feedback so "Saved." never lingers over unsaved changes.
  const touch = () => {
    setSuccess(false);
    setSaveError(null);
  };

  // Stable identity (the memoized chips depend on it). Inlines `touch()`.
  const toggleId = useCallback((id: string) => {
    setSuccess(false);
    setSaveError(null);
    setDraftIds((d) => (d.includes(id) ? d.filter((x) => x !== id) : [...d, id]));
  }, []);

  // Keyboard fast path: type a few letters, press Enter, the top match toggles
  // and the filter clears so the next name can be typed straight away.
  const handleFilterKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const top = visibleCompanies[0];
    if (query && top) {
      toggleId(top.id);
      setFilter('');
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSuccess(false);
    setSaveError(null);
    try {
      await save(idsToSave, draftAutoEnroll);
      setSuccess(true);
    } catch (err) {
      setSaveError(extractErrorMessage(err, 'Failed to save changes'));
    } finally {
      setSaving(false);
    }
  };

  if (loading && ids === null) {
    return (
      <Paper sx={{ p: 4 }}>
        <LoadingState />
      </Paper>
    );
  }

  return (
    <Accordion
      defaultExpanded
      disableGutters
      sx={{
        borderRadius: 1,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 4, py: 1 }}>
        <Typography variant="h6">Saved companies</Typography>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ ml: 1, alignSelf: 'center' }}
          data-testid="saved-companies-summary"
        >
          {mode === 'all' ? 'All companies' : `${selectedCount} selected`}
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 4, pb: 4, pt: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Which companies appear in your Recent Job Postings feed.
        </Typography>

        <RadioGroup
          aria-label="Companies to show"
          value={mode}
          onChange={(_, value) => {
            touch();
            setMode(value as CompanyMode);
          }}
        >
          <FormControlLabel value="all" control={<Radio />} label="All companies" />
          <FormControlLabel value="custom" control={<Radio />} label="Only these companies" />
        </RadioGroup>

        {mode === 'custom' && (
          <Stack spacing={1.5} sx={{ mt: 1, pl: { xs: 0, sm: 4 } }}>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              alignItems={{ xs: 'stretch', sm: 'center' }}
            >
              <TextField
                size="small"
                label="Find a company"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                onKeyDown={handleFilterKeyDown}
                sx={{ flex: 1, maxWidth: { sm: 320 } }}
              />
              <Box sx={{ flex: 1 }} />
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="body2" color="text.secondary" sx={{ mr: 1 }}>
                  {selectedCount} selected
                </Typography>
                <Button
                  size="small"
                  aria-label="Select all companies"
                  onClick={() => {
                    touch();
                    setDraftIds(ALL_IDS);
                  }}
                >
                  Select all
                </Button>
                {/* aria-label keeps this distinct from the company chip named "Clear". */}
                <Button
                  size="small"
                  aria-label="Clear selected companies"
                  disabled={selectedCount === 0}
                  onClick={() => {
                    touch();
                    setDraftIds([]);
                  }}
                >
                  Clear
                </Button>
              </Stack>
            </Stack>

            {selectedCount === 0 && (
              <Typography variant="caption" color="text.secondary">
                Nothing picked yet — your feed still shows every company.
              </Typography>
            )}

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {visibleCompanies.map((c) => (
                <CompanyChip
                  key={c.id}
                  id={c.id}
                  name={c.name}
                  selected={draftSet.has(c.id)}
                  onToggle={toggleId}
                />
              ))}
              {visibleCompanies.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  No companies match &ldquo;{filter.trim()}&rdquo;.
                </Typography>
              )}
            </Box>

            <FormControlLabel
              control={
                <Checkbox
                  checked={draftAutoEnroll}
                  onChange={(e) => {
                    touch();
                    setDraftAutoEnroll(e.target.checked);
                  }}
                />
              }
              label="Auto-add new companies"
            />
          </Stack>
        )}

        <SectionSaveButton
          dirty={dirty}
          saving={saving}
          success={success}
          error={saveError ?? error}
          onSave={handleSave}
          label="Save companies"
        />
      </AccordionDetails>
    </Accordion>
  );
}
