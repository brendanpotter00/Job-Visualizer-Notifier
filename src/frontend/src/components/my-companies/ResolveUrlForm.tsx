import { useState, type FormEvent } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';

interface ResolveUrlFormProps {
  /** Called with the trimmed URL. Never called while `resolving` or with an empty value. */
  onSubmit: (url: string) => void;
  /** Drives the disabled/progress state. Owned by the page's mutation. */
  resolving: boolean;
}

/**
 * The careers-URL input.
 *
 * Submitting is wired through a real `<form>` so Enter works for free rather
 * than needing a keydown handler. The field keeps its value while a check is in
 * flight (disabled, not cleared) so a failed URL can be edited and retried
 * instead of retyped.
 */
export function ResolveUrlForm({ onSubmit, resolving }: ResolveUrlFormProps) {
  const [value, setValue] = useState('');

  const trimmed = value.trim();
  const canSubmit = trimmed.length > 0 && !resolving;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit(trimmed);
  };

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems="flex-start">
        <TextField
          fullWidth
          label="Careers page URL"
          placeholder="https://example.com/careers"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={resolving}
          helperText="Paste a link to a company's job listings and we'll see whether we can read them."
          slotProps={{ htmlInput: { 'aria-label': 'Careers page URL', maxLength: 2048 } }}
        />
        <Button
          type="submit"
          variant="contained"
          disabled={!canSubmit}
          sx={{ mt: { xs: 0, sm: 1 }, flexShrink: 0 }}
          startIcon={resolving ? <CircularProgress size={16} color="inherit" /> : undefined}
        >
          {resolving ? 'Checking…' : 'Check URL'}
        </Button>
      </Stack>
    </Box>
  );
}
