import { useState, useEffect, useMemo } from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Alert from '@mui/material/Alert';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Chip from '@mui/material/Chip';
import { COMPANIES } from '../../config/companies';
import { useEnabledCompanies } from '../../features/preferences/useEnabledCompanies';
import { MultiSelectAutocomplete } from '../shared/filters/MultiSelectAutocomplete';

export function EnabledCompaniesSection() {
  const { ids, loading, error, save } = useEnabledCompanies();

  const [draft, setDraft] = useState<string[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(ids ?? []);
  }, [ids]);

  const idToName = useMemo(() => new Map(COMPANIES.map((c) => [c.id, c.name])), []);
  const nameToId = useMemo(() => new Map(COMPANIES.map((c) => [c.name, c.id])), []);
  const allNames = useMemo(() => COMPANIES.map((c) => c.name).sort(), []);

  const selectedNames = useMemo(
    () =>
      draft
        .map((id) => idToName.get(id))
        .filter((n): n is string => Boolean(n))
        .sort(),
    [draft, idToName]
  );

  const availableNames = useMemo(() => {
    const selectedSet = new Set(selectedNames);
    return allNames.filter((n) => !selectedSet.has(n));
  }, [allNames, selectedNames]);

  const canonicalDraft = useMemo(() => [...new Set(draft)].sort(), [draft]);
  const canonicalSaved = useMemo(() => [...(ids ?? [])].sort(), [ids]);
  const isDirty = canonicalDraft.join('|') !== canonicalSaved.join('|');

  const handleSave = async () => {
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      await save(canonicalDraft);
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save changes');
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

  const handleAdd = (name: string) => {
    const id = nameToId.get(name);
    if (!id) return;
    setSaveSuccess(false);
    setDraft((d) => (d.includes(id) ? d : [...d, id]));
  };

  const handleRemove = (name: string) => {
    const id = nameToId.get(name);
    if (!id) return;
    setSaveSuccess(false);
    setDraft((d) => d.filter((x) => x !== id));
  };

  if (loading && ids === null) {
    return (
      <Paper sx={{ p: 4, mt: 3, textAlign: 'center' }}>
        <CircularProgress />
      </Paper>
    );
  }

  const selectedCount = selectedNames.length;

  return (
    <Paper sx={{ p: 4, mt: 3 }}>
      <Typography variant="h6" gutterBottom>
        Recent Jobs Companies
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Pick which companies show up in your Recent Job Postings feed. Leave empty to see all.
      </Typography>

      <Box sx={{ mb: 3 }}>
        <MultiSelectAutocomplete
          label="Companies"
          options={availableNames}
          value={[]}
          onAdd={handleAdd}
          onRemove={handleRemove}
          placeholder="Add a company..."
          minWidth={0}
        />
      </Box>

      <Box sx={{ mb: 3 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            Your selected companies
          </Typography>
          <Chip
            label={selectedCount}
            size="small"
            data-testid="selected-count"
            sx={{ height: 20, fontSize: '0.7rem', fontWeight: 700, px: 0.5 }}
          />
        </Stack>

        {selectedCount === 0 ? (
          <Box
            sx={{
              p: 2.5,
              border: '1px dashed',
              borderColor: 'divider',
              borderRadius: 1,
              textAlign: 'center',
            }}
          >
            <Typography variant="body2" color="text.secondary">
              No companies selected. You'll see postings from all companies.
            </Typography>
          </Box>
        ) : (
          <Box
            sx={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 1,
              p: 1.5,
              bgcolor: 'action.hover',
              borderRadius: 1,
            }}
          >
            {selectedNames.map((name) => (
              <Chip
                key={name}
                label={name}
                onDelete={() => handleRemove(name)}
                color="primary"
                variant="filled"
                size="small"
                data-testid={`selected-chip-${name}`}
              />
            ))}
          </Box>
        )}
      </Box>

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
