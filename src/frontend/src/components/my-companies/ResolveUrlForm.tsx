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
  /**
   * Refuse the submit outright — today, the caller has no adds left this month.
   *
   * SEPARATE from `status`, because it is a different kind of "no". `status` is
   * transient ("wait, this is running") and re-enables itself; this one does not
   * change until the 1st, and the counter above the form is its whole explanation.
   * The FIELD stays editable on purpose: someone can still paste and read a URL
   * they are queuing up for next month, and disabling the input would look like
   * the page was broken rather than the allowance spent.
   *
   * It is a courtesy, never the control. The server refuses over quota regardless
   * of what this button does — see the 422 `monthly_limit_reached`.
   */
  disabled?: boolean;
}

/**
 * The careers-URL input, and the ONLY action in the add flow.
 *
 * Submitting is wired through a real `<form>` so Enter works for free rather
 * than needing a keydown handler. The field keeps its value while a check is in
 * flight (disabled, not cleared) so a failed URL can be edited and retried
 * instead of retyped.
 *
 * The label says "Add company", never "Check URL", because this button no longer only
 * reads: a URL with no supported ATS behind it goes straight into a one-time discovery
 * that costs an LLM call and a headless browser session. A button promising a read-only
 * check that quietly spends money is a worse defect than the extra click it replaced, so
 * the label names the thing the user is actually asking for — the company ends up tracked
 * — and the helper text below, plus the page's intro alert, name which of the two routes
 * it takes to get there. Whatever this label becomes, it must never shrink back to
 * promising a read-only check.
 *
 * The in-flight labels stay phase-specific ("Checking…" then "Setting up…") rather than
 * echoing the button: they are the only place the user can see WHICH half of the action
 * is running, and the discovery half is the slow, expensive one.
 *
 * THE FIELD COPY IS SHORT ON PURPOSE, and it was not always. The helper text used to
 * carry the whole branch ("if it's a board we already read you'll see what we found
 * before anything is tracked; if it isn't, we start a one-time setup to learn how to
 * read it") — three clauses under a one-line input, which is a length people skip, and
 * skipped help is worse than none. The page's intro alert already states both outcomes
 * and IS the consent; this line only has to say what to paste. So: the label names the
 * thing ("Job board link"), the placeholder repeats the instruction where an empty box
 * is already looking at you, and the helper adds the one qualifier that actually changes
 * what a user pastes — EXACT, and from the company. Whatever this becomes, it must not
 * grow back into a second copy of the alert.
 */
export function ResolveUrlForm({ onSubmit, status, disabled = false }: ResolveUrlFormProps) {
  const [value, setValue] = useState('');

  const busy = status !== 'idle';
  const trimmed = value.trim();
  const canSubmit = trimmed.length > 0 && !busy && !disabled;

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
          label="Job board link"
          placeholder="Paste the company’s job board"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={busy}
          helperText="Paste the exact job board link, directly from the company."
          slotProps={{ htmlInput: { 'aria-label': 'Job board link', maxLength: 2048 } }}
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
              : 'Add company'}
        </Button>
      </Stack>
    </Box>
  );
}
