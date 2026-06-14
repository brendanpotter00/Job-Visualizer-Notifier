import { useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControl from '@mui/material/FormControl';
import IconButton from '@mui/material/IconButton';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Select from '@mui/material/Select';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import {
  useOverrideAliasMutation,
  type AliasRow,
  type LocationSpec,
} from '../../../features/admin/adminApi';
import { extractErrorMessage } from '../../../lib/errors';

interface AliasEditDialogProps {
  open: boolean;
  alias: AliasRow | null;
  onClose: () => void;
}

const KINDS: LocationSpec['kind'][] = ['city', 'region', 'country', 'remote'];

function emptyRow(): LocationSpec {
  return {
    canonicalName: '',
    kind: 'city',
    city: '',
    region: '',
    country: '',
    remoteScope: '',
  };
}

/**
 * Normalizes a row to satisfy the cross-field rules:
 *   - remote → city is disabled/empty
 *   - non-remote → remoteScope is disabled/empty
 * Applied both on render (to disable inputs) and at save time (to send a
 * clean payload), so the constraint can't be bypassed by editing a field and
 * then switching kind.
 */
function applyKindRules(row: LocationSpec): LocationSpec {
  if (row.kind === 'remote') {
    return { ...row, city: '' };
  }
  return { ...row, remoteScope: '' };
}

function fromCanonicalLocations(alias: AliasRow): LocationSpec[] {
  if (alias.locations.length === 0) return [emptyRow()];
  return alias.locations.map((loc) => {
    const kind = (KINDS.includes(loc.kind as LocationSpec['kind'])
      ? loc.kind
      : 'city') as LocationSpec['kind'];
    return applyKindRules({
      canonicalName: loc.canonicalName,
      kind,
      city: loc.city ?? '',
      region: loc.region ?? '',
      country: loc.country ?? '',
      remoteScope: loc.remoteScope ?? '',
    });
  });
}

export function AliasEditDialog({ open, alias, onClose }: AliasEditDialogProps) {
  const [rows, setRows] = useState<LocationSpec[]>([emptyRow()]);
  const [error, setError] = useState<string | null>(null);
  const [overrideAlias, { isLoading }] = useOverrideAliasMutation();

  // Re-seed the form whenever the dialog (re)opens for a possibly-different
  // alias. We track the open alias identity and re-seed *during render* —
  // React's documented alternative to a reset effect
  // (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes).
  // ``null`` is the seed key while closed so reopening always re-runs.
  const seedKey = open && alias ? alias.rawText : null;
  const [lastSeedKey, setLastSeedKey] = useState<string | null>(null);
  if (seedKey !== lastSeedKey) {
    setLastSeedKey(seedKey);
    if (open && alias) {
      setRows(fromCanonicalLocations(alias));
      setError(null);
    }
  }

  const updateRow = (index: number, patch: Partial<LocationSpec>) => {
    setRows((prev) =>
      prev.map((row, i) => (i === index ? applyKindRules({ ...row, ...patch }) : row))
    );
  };

  const addRow = () => setRows((prev) => [...prev, emptyRow()]);
  const removeRow = (index: number) =>
    setRows((prev) => (prev.length === 1 ? prev : prev.filter((_, i) => i !== index)));

  const canSave =
    !isLoading && rows.length > 0 && rows.every((r) => r.canonicalName.trim().length > 0);

  const handleSave = async () => {
    if (!alias) return;
    setError(null);
    // Re-apply the kind rules and trim before sending so we never persist a
    // city on a remote spec or a stray remoteScope on a city.
    const locations: LocationSpec[] = rows.map((row) => {
      const cleaned = applyKindRules({ ...row, canonicalName: row.canonicalName.trim() });
      return {
        canonicalName: cleaned.canonicalName,
        kind: cleaned.kind,
        city: cleaned.city?.trim() || null,
        region: cleaned.region?.trim() || null,
        country: cleaned.country?.trim() || null,
        remoteScope: cleaned.remoteScope?.trim() || null,
      };
    });
    try {
      await overrideAlias({ rawText: alias.rawText, locations }).unwrap();
      onClose();
    } catch (err) {
      // A literal "/" in rawText may fail through the proxy — surface the
      // real error rather than swallowing it.
      setError(extractErrorMessage(err, 'Failed to save alias override'));
    }
  };

  return (
    <Dialog open={open} onClose={isLoading ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>Edit alias mapping</DialogTitle>
      <DialogContent dividers>
        {alias && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Raw text:{' '}
            <Box component="span" sx={{ fontFamily: 'monospace', color: 'text.primary' }}>
              {alias.rawText}
            </Box>
          </Typography>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Stack spacing={2}>
          {rows.map((row, index) => {
            const isRemote = row.kind === 'remote';
            return (
              <Paper key={index} variant="outlined" sx={{ p: 2 }}>
                <Stack
                  direction="row"
                  spacing={1}
                  sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}
                >
                  <Typography variant="subtitle2">Location {index + 1}</Typography>
                  <IconButton
                    size="small"
                    aria-label={`Remove location ${index + 1}`}
                    onClick={() => removeRow(index)}
                    disabled={rows.length === 1}
                  >
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </Stack>
                <Stack spacing={2}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                    <FormControl size="small" sx={{ minWidth: 140 }}>
                      <InputLabel id={`kind-label-${index}`}>Kind</InputLabel>
                      <Select
                        labelId={`kind-label-${index}`}
                        label="Kind"
                        value={row.kind}
                        onChange={(e) =>
                          updateRow(index, { kind: e.target.value as LocationSpec['kind'] })
                        }
                      >
                        {KINDS.map((kind) => (
                          <MenuItem key={kind} value={kind}>
                            {kind}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                    <TextField
                      size="small"
                      label="Canonical name"
                      required
                      fullWidth
                      value={row.canonicalName}
                      error={row.canonicalName.trim().length === 0}
                      onChange={(e) => updateRow(index, { canonicalName: e.target.value })}
                    />
                  </Stack>
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                    <TextField
                      size="small"
                      label="City"
                      fullWidth
                      value={row.city ?? ''}
                      disabled={isRemote}
                      onChange={(e) => updateRow(index, { city: e.target.value })}
                    />
                    <TextField
                      size="small"
                      label="Region"
                      fullWidth
                      value={row.region ?? ''}
                      onChange={(e) => updateRow(index, { region: e.target.value })}
                    />
                  </Stack>
                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                    <TextField
                      size="small"
                      label="Country"
                      fullWidth
                      value={row.country ?? ''}
                      onChange={(e) => updateRow(index, { country: e.target.value })}
                    />
                    <TextField
                      size="small"
                      label="Remote scope"
                      fullWidth
                      value={row.remoteScope ?? ''}
                      disabled={!isRemote}
                      onChange={(e) => updateRow(index, { remoteScope: e.target.value })}
                    />
                  </Stack>
                </Stack>
              </Paper>
            );
          })}
        </Stack>

        <Button startIcon={<AddIcon />} onClick={addRow} sx={{ mt: 2 }}>
          Add location
        </Button>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isLoading}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSave} disabled={!canSave}>
          {isLoading ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
