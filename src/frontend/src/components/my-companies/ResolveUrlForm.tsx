import { useState, type FormEvent } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';

interface ResolveUrlFormProps {
  /** Called with the trimmed URL. Never called while busy or with an empty value. */
  onSubmit: (url: string) => void;
  /**
   * The add is in flight.
   *
   * ONE boolean, and it used to be a three-state `status` (`idle | checking |
   * setting-up`) plus a `busy` flag the page held across both. That machinery existed
   * because the submit ran a preview resolve and then MAYBE a second call, and the two
   * mutations were both momentarily idle in between — so anything derived from them
   * blinked the button back to "ready" mid-action. There is one call now, so there is
   * one phase, and a label naming which half is running would name a half that no
   * longer exists.
   */
  busy: boolean;
  /**
   * Refuse the submit outright — today, the caller has no adds left this month.
   *
   * SEPARATE from `busy`, because it is a different kind of "no". `busy` is
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
 * than needing a keydown handler. The field keeps its value while the add is in
 * flight (disabled, not cleared) so a failed URL can be edited and retried
 * instead of retyped.
 *
 * ONE PRESS, ONE OUTCOME, and that is the change this component exists to carry.
 * Pressing this used to open a preview card ("Found 377 open jobs on Ashby") that the
 * user then had to confirm with a second **Track this company** button. The second
 * press is gone: this one adds the company, or fails and says why. The label already
 * said "Add company" and now it is literally true — and it must never shrink back to
 * promising a read-only check, because a URL with no supported board behind it goes
 * straight into a one-time discovery that costs an LLM call and a headless browser
 * session.
 *
 * THE FIELD COPY IS SHORT ON PURPOSE, and it was not always. The helper text used to
 * carry the whole branch ("if it's a board we already read you'll see what we found
 * before anything is tracked; if it isn't, we start a one-time setup to learn how to
 * read it") — three clauses under a one-line input, which is a length people skip, and
 * skipped help is worse than none. So the helper says only WHAT TO PASTE, and the spend
 * sentence under the button says WHAT PRESSING IT COSTS. Two jobs, two lines; they must
 * not merge back into one paragraph.
 *
 * THE SPEND SENTENCE LIVES HERE, glued to the button, and it replaced a blue consent
 * alert that used to sit above the whole form ("the consent alert can be completely
 * removed"). It is the only place the page says that pressing Add company can start
 * paid work on the user's behalf, so it is never behind a click, never inside the
 * how-to block, and never in a component the button could be lifted out of.
 */
export function ResolveUrlForm({ onSubmit, busy, disabled = false }: ResolveUrlFormProps) {
  const [value, setValue] = useState('');

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
          label="Careers page link"
          placeholder="e.g. stripe.com/jobs"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          disabled={busy}
          // THE ONE RULE THE PRODUCT CANNOT YET ENFORCE, so it has to be written down.
          // `_NEVER_MATCH_DOMAINS` (company_name_match.py) does hold linkedin.com and
          // indeed.com, but it is a DENYLIST consulted on the wrong rung — it is the "is
          // this already a public company" guess, not a submit-time refusal — and it
          // misses dice.com, monster.com and hiring.cafe anyway. So an aggregator URL
          // resolves, finds no board, reaches `no_ats_detected`, and `no_ats_detected` is
          // precisely the reason the add endpoint routes into PAID discovery: a headless
          // browser session, an LLM call, and one of the user's monthly adds.
          //
          // "not LinkedIn or Indeed" is here ONLY because the how-to video that was going
          // to say it does not exist yet. Delete that clause the day
          // `HOW_IT_WORKS_VIDEO_SRC` (AddCompanyHowTo.tsx) stops being null, and not
          // before: it is currently the last statement of this rule anywhere in the app.
          helperText="Paste the link to the company’s own careers page, not LinkedIn or Indeed. Any page of their job list works."
          slotProps={{ htmlInput: { 'aria-label': 'Careers page link', maxLength: 2048 } }}
        />
        <Button
          type="submit"
          variant="contained"
          disabled={!canSubmit}
          sx={{ mt: { xs: 0, sm: 1 }, flexShrink: 0 }}
          startIcon={busy ? <CircularProgress size={16} color="inherit" /> : undefined}
        >
          {busy ? 'Adding…' : 'Add company'}
        </Button>
      </Stack>

      {/* UNDER THE BUTTON, in both the empty and the populated state, never behind a
          disclosure. See the docstring: this sentence is the whole consent. */}
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1.75 }}>
        If this board is new to us,{' '}
        <Box component="strong" sx={{ color: 'text.primary' }}>
          Add company
        </Box>{' '}
        starts a one-time setup right away, about a minute.
      </Typography>
    </Box>
  );
}
