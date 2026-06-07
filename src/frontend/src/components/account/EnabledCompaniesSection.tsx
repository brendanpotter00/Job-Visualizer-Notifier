import { useState, useEffect, useMemo } from 'react';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Alert from '@mui/material/Alert';
import Stack from '@mui/material/Stack';
import Box from '@mui/material/Box';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import { COMPANIES } from '../../config/companies';
import { useEnabledCompanies } from '../../features/preferences/useEnabledCompanies';
import { CompanySearchAddInput } from './CompanySearchAddInput';
import { SelectedCompaniesPanel } from './SelectedCompaniesPanel';
import { BrowseCompaniesAccordion } from './BrowseCompaniesAccordion';
import { CompanyChipGrid } from './CompanyChipGrid';
import { LoadingState } from '../shared/LoadingIndicator';
import { extractErrorMessage } from '../../lib/errors';

export function EnabledCompaniesSection() {
  const { ids, autoEnroll, loading, error, save } = useEnabledCompanies();

  const [draft, setDraft] = useState<string[]>([]);
  const [draftAutoEnroll, setDraftAutoEnroll] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [searchInputValue, setSearchInputValue] = useState('');

  useEffect(() => {
    setDraft(ids ?? []);
    // Clear a stale save error when ids change (successful save or external
    // reload) so it can't shadow a newer slice-level error in the Alert.
    setSaveError(null);
  }, [ids]);

  const savedAutoEnroll = autoEnroll ?? true;
  useEffect(() => {
    setDraftAutoEnroll(savedAutoEnroll);
  }, [savedAutoEnroll]);

  useEffect(() => {
    if (error) setSaveError(null);
  }, [error]);

  const sortedCompanies = useMemo(
    () => [...COMPANIES].sort((a, b) => a.name.localeCompare(b.name)),
    []
  );

  const draftSet = useMemo(() => new Set(draft), [draft]);

  const selectedCompanies = useMemo(
    () => sortedCompanies.filter((c) => draftSet.has(c.id)),
    [sortedCompanies, draftSet]
  );

  const canonicalDraft = useMemo(() => [...new Set(draft)].sort(), [draft]);
  const canonicalSaved = useMemo(() => [...(ids ?? [])].sort(), [ids]);
  const isDirty =
    canonicalDraft.join('|') !== canonicalSaved.join('|') ||
    draftAutoEnroll !== savedAutoEnroll;

  const handleSave = async () => {
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      await save(canonicalDraft, draftAutoEnroll);
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(extractErrorMessage(err, 'Failed to save changes'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleSelectAll = () => {
    setDraft(COMPANIES.map((c) => c.id));
    setSaveSuccess(false);
  };

  const handleClear = () => {
    setDraft([]);
    setSaveSuccess(false);
  };

  const handleAddId = (id: string) => {
    setSaveSuccess(false);
    setDraft((d) => (d.includes(id) ? d : [...d, id]));
  };

  const handleRemoveId = (id: string) => {
    setSaveSuccess(false);
    setDraft((d) => d.filter((x) => x !== id));
  };

  const handleToggleId = (id: string) => {
    setSaveSuccess(false);
    setDraft((d) => (d.includes(id) ? d.filter((x) => x !== id) : [...d, id]));
  };

  if (loading && ids === null) {
    return (
      <Paper sx={{ p: 4, mt: 3 }}>
        <LoadingState />
      </Paper>
    );
  }

  return (
    <Paper sx={{ p: 4, mt: 3 }}>
      <Typography variant="h6" gutterBottom>
        Recent jobs page companies
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Pick which companies show up in your Recent Job Postings feed. Leave empty to see all.
      </Typography>

      <Box sx={{ mb: 2 }}>
        <CompanySearchAddInput
          companies={sortedCompanies}
          selectedIds={draftSet}
          inputValue={searchInputValue}
          onInputChange={setSearchInputValue}
          onAdd={handleAddId}
        />
      </Box>

      <Box sx={{ mb: 3 }}>
        <BrowseCompaniesAccordion
          selectedCount={selectedCompanies.length}
          totalCount={sortedCompanies.length}
        >
          <CompanyChipGrid
            companies={sortedCompanies}
            selectedIds={draftSet}
            onToggle={handleToggleId}
          />
        </BrowseCompaniesAccordion>
      </Box>

      <Box sx={{ mb: 2 }}>
        <FormControlLabel
          control={
            <Switch
              checked={draftAutoEnroll}
              onChange={(e) => {
                setSaveSuccess(false);
                setDraftAutoEnroll(e.target.checked);
              }}
              slotProps={{
                input: { 'aria-label': 'Auto-include newly added companies' },
              }}
            />
          }
          label="Auto-include newly added companies"
        />
        <Typography variant="caption" color="text.secondary" display="block">
          When on, companies we add later show up in your feed automatically. You can remove any
          you don&apos;t want.
        </Typography>
      </Box>

      <SelectedCompaniesPanel
        selectedCompanies={selectedCompanies}
        onRemove={handleRemoveId}
      />

      <Stack direction="row" spacing={1} sx={{ mb: 3 }}>
        <Button variant="outlined" size="small" onClick={handleSelectAll}>
          Select All
        </Button>
        <Button
          variant="outlined"
          size="small"
          onClick={handleClear}
          disabled={draft.length === 0}
        >
          Clear
        </Button>
      </Stack>

      {saveSuccess && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Preferences saved.
        </Alert>
      )}

      {(saveError || error) && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {saveError ?? error}
        </Alert>
      )}

      <Button
        variant="contained"
        onClick={handleSave}
        disabled={!isDirty || isSaving}
        fullWidth
      >
        {isSaving ? 'Saving...' : 'Save Changes'}
      </Button>
    </Paper>
  );
}
