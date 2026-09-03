import { useState, type FormEvent } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import {
  classifyCompanyInput,
  COMPANY_NAME_MAX_CHARS,
} from '../../features/userCompanies/companyInput';

/**
 * What a value over the cap is told, and it has to be an INSTRUCTION rather than a
 * measurement. The server's own refusal is a raw Pydantic 422 reading "String should
 * have at most 60 characters", which is true, arrives after a round-trip, and tells
 * nobody what to do next. The thing to do next is paste a link.
 */
const TOO_LONG_FOR_A_NAME =
  'That’s too long to be a company name — paste the link to their careers page instead.';

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
  /**
   * Accept a typed company NAME as well as a URL — label, placeholder and helper
   * text all change with it.
   *
   * A prop rather than reading the flag here, so this component stays a dumb
   * input and the page owns which of the two submit paths a value takes. OFF
   * renders exactly the URL-only wording that shipped before, which matters
   * because the wording is a promise: with the server flag off a typed name is
   * a 503, so the box must not invite one.
   */
  allowName?: boolean;
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
 * skipped help is worse than none. So the helper says only WHAT TO PASTE. It must not
 * grow back into the spend explanation now that the sentence which carried that job is
 * gone (see below) — a helper nobody finishes reading is not a disclosure.
 *
 * THE SPEND SENTENCE IS GONE, removed at the owner's request on 2026-09-02, and this
 * note is here so nobody re-derives it from first principles and puts it back by
 * accident. It read "If this board is new to us, Add company starts a one-time setup
 * right away, about a minute", sat glued under the button, and had itself replaced an
 * earlier blue consent alert above the form.
 *
 * What its removal costs, stated plainly because it is a real trade: nothing on this
 * page now says that pressing **Add company** on a board we do not already read can
 * start paid work — a headless browser session and a model call — on the user's
 * behalf. The spend is still bounded server-side (20 adds per UTC month, a 10/60s
 * burst limit, and `CUSTOM_COMPANY_DISCOVERY_ENABLED`), so the exposure is capped;
 * what is missing is the disclosure, not the cap.
 *
 * If it ever comes back it belongs HERE — under the button, in both the empty and the
 * populated state, never behind a click and never inside the how-to block.
 */
export function ResolveUrlForm({
  onSubmit,
  busy,
  disabled = false,
  allowName = false,
}: ResolveUrlFormProps) {
  const [value, setValue] = useState('');
  const [tooLong, setTooLong] = useState(false);

  const trimmed = value.trim();
  const canSubmit = trimmed.length > 0 && !busy && !disabled;

  /**
   * THE LIMIT FOLLOWS THE CLASSIFICATION, NOT THE FIELD.
   *
   * One box takes two kinds of value with two different ceilings: a URL may be 2048
   * characters and a name may be 60, and the field cannot know which it is holding
   * until the press. So the `maxLength` stays at the URL's ceiling — truncating a
   * pasted link at 60 would be far worse than any error message — and the name's cap
   * is checked HERE, at submit, on the value we have just classified.
   *
   * Before the request, deliberately. Sending it would spend a paid Browserbase
   * search on an input we can already tell is invalid, and buy back a raw Pydantic
   * 422 the user cannot act on. The server keeps its own cap; that is the real
   * enforcement and this is only the part that is kind about it.
   *
   * Gated on `allowName`, because with the flag off nothing is a name — every value
   * goes to the URL path exactly as it did before the name box existed.
   */
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    if (allowName) {
      const classified = classifyCompanyInput(trimmed);
      if (
        classified.kind === 'name' &&
        classified.name.length > COMPANY_NAME_MAX_CHARS
      ) {
        setTooLong(true);
        return;
      }
    }
    setTooLong(false);
    onSubmit(trimmed);
  };

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems="flex-start">
        <TextField
          fullWidth
          label={allowName ? 'Company name or careers page link' : 'Careers page link'}
          placeholder={allowName ? 'e.g. Stripe, or stripe.com/jobs' : 'e.g. stripe.com/jobs'}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            // The complaint is about a value that no longer exists the moment it is
            // edited. Left up, it would sit under a field the user has already fixed.
            setTooLong(false);
          }}
          disabled={busy}
          error={tooLong}
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
          helperText={
            tooLong
              ? TOO_LONG_FOR_A_NAME
              : allowName
                ? 'Type the company’s name, or paste the link to their own careers page — not LinkedIn or Indeed. Any page of their job list works.'
                : 'Paste the link to the company’s own careers page, not LinkedIn or Indeed. Any page of their job list works.'
          }
          slotProps={{
            htmlInput: {
              'aria-label': allowName
                ? 'Company name or careers page link'
                : 'Careers page link',
              // The URL ceiling, and it stays that for every value. A name over its
              // own (much shorter) cap is REFUSED at submit rather than truncated
              // here — see `handleSubmit`. Truncating would silently search for
              // something the user did not type.
              maxLength: 2048,
            },
          }}
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

    </Box>
  );
}
