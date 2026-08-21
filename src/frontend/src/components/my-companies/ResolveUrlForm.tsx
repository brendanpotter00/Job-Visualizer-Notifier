import { useState, type FormEvent } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';

interface ResolveUrlFormProps {
  /** Called with the trimmed URL. Never called while busy or with an empty value. */
  onSubmit: (url: string) => void;
  /**
   * Which half of the submit action is in flight. ONE prop rather than two booleans
   * because the action is resolve-then-maybe-discover: between the resolve settling and
   * the discovery POST being dispatched both mutations are momentarily idle, and a
   * `checking || settingUp` flag derived from them would blink the button back to
   * "ready" mid-action — inviting a second submit that starts a second paid discovery.
   * The page owns this value and holds it non-`idle` across the whole action.
   */
  status: 'idle' | 'checking' | 'setting-up';
}

/**
 * The careers-URL input, and the ONLY action in the add flow.
 *
 * Submitting is wired through a real `<form>` so Enter works for free rather
 * than needing a keydown handler. The field keeps its value while a check is in
 * flight (disabled, not cleared) so a failed URL can be edited and retried
 * instead of retyped.
 *
 * The label says "Check & set up", not "Check URL", because this button no longer only
 * reads: a URL with no supported ATS behind it goes straight into a one-time discovery
 * that costs an LLM call and a headless browser session. A button promising a read-only
 * check that quietly spends money is a worse defect than the extra click it replaced, so
 * the label and the helper text below both name the second outcome up front.
 */
export function ResolveUrlForm({ onSubmit, status }: ResolveUrlFormProps) {
  const [value, setValue] = useState('');

  const busy = status !== 'idle';
  const trimmed = value.trim();
  const canSubmit = trimmed.length > 0 && !busy;

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
          disabled={busy}
          helperText="Paste a link to a company's job listings. If it's a board we already read you'll see what we found before anything is tracked; if it isn't, we start a one-time setup to learn how to read it."
          slotProps={{ htmlInput: { 'aria-label': 'Careers page URL', maxLength: 2048 } }}
        />
        <Button
          type="submit"
          variant="contained"
          disabled={!canSubmit}
          sx={{ mt: { xs: 0, sm: 1 }, flexShrink: 0 }}
          startIcon={busy ? <CircularProgress size={16} color="inherit" /> : undefined}
        >
          {status === 'setting-up'
            ? 'Setting up…'
            : status === 'checking'
              ? 'Checking…'
              : 'Check & set up'}
        </Button>
      </Stack>
    </Box>
  );
}
