import Paper from '@mui/material/Paper';
import Button from '@mui/material/Button';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';

export interface PreferencesSaveBarProps {
  isDirty: boolean;
  isSaving: boolean;
  saveSuccess: boolean;
  saveError: string | null;
  onSave: () => void;
}

/**
 * The single, explicit Save bar for the Preferences page. There is NO per-card
 * autosave: this bar commits every card's draft (time windows, locations,
 * active lists, and all keyword-list create/update/delete operations) at once.
 */
export function PreferencesSaveBar({
  isDirty,
  isSaving,
  saveSuccess,
  saveError,
  onSave,
}: PreferencesSaveBarProps) {
  return (
    <Paper sx={{ p: 3 }}>
      {saveSuccess && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Preferences saved.
        </Alert>
      )}
      {saveError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {saveError}
        </Alert>
      )}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button variant="contained" onClick={onSave} disabled={!isDirty || isSaving}>
          {isSaving ? 'Saving...' : 'Save changes'}
        </Button>
      </Box>
    </Paper>
  );
}
