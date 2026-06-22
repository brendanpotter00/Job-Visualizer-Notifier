import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Alert from '@mui/material/Alert';
import { ErrorState } from '../shared/ErrorDisplay';

export interface SectionSaveButtonProps {
  /** Whether this section has unsaved changes (enables the button). */
  dirty: boolean;
  /** Whether this section's save request is in flight. */
  saving: boolean;
  /** Show the "Saved" confirmation (suppressed once the section is edited again). */
  success: boolean;
  /** Save error message for this section, or null. */
  error: string | null;
  onSave: () => void;
  /** Button label (defaults to "Save"). */
  label?: string;
}

/**
 * Per-section Save control for the Saved Filters page. Each settings section
 * (time windows, locations, active keyword list) renders its own button so the
 * Save action sits directly beneath the inputs the user just edited — they no
 * longer have to scroll to a single bottom bar (the previous `SavedFiltersSaveBar`).
 * A save still issues one request for the whole settings object; this component
 * is only the trigger plus that section's inline success/error feedback.
 */
export function SectionSaveButton({
  dirty,
  saving,
  success,
  error,
  onSave,
  label = 'Save',
}: SectionSaveButtonProps) {
  return (
    <Stack spacing={2} sx={{ mt: 3 }}>
      {error && <ErrorState inline message={error} />}
      {success && !dirty && <Alert severity="success">Saved.</Alert>}
      <Box>
        <Button variant="contained" onClick={onSave} disabled={!dirty || saving}>
          {saving ? 'Saving…' : label}
        </Button>
      </Box>
    </Stack>
  );
}
