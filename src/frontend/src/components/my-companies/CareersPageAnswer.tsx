import Button from '@mui/material/Button';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';

interface CareersPageAnswerProps {
  /** What the user typed, echoed so every sentence names its own subject. */
  query: string;
  /** The company's own careers page, or null when nothing named them. */
  careersUrl: string | null;
  /** How many boards came back that the gate could not confirm. 0 = none came back. */
  unconfirmedCount: number;
  /**
   * Nothing the search found was `autoAddable`, so THIS is the answer and it leads
   * the page. False means a confirmed board is on screen above and this is the
   * footnote beside it, which is the shape that shipped.
   */
  lead: boolean;
  /** Track the careers page. Takes the same URL the paste-a-link path takes. */
  onUse: (url: string) => void;
  /** An add is in flight — the button is inert while one is. */
  busy: boolean;
}

/**
 * The careers page, presented as the answer it usually is.
 *
 * WHY THIS IS ITS OWN BLOCK, AND WHY IT GOES FIRST. Typing "meta" returned five
 * real job boards, none of them Meta's — and the page rendered them as five large
 * cards with black "Track this one" buttons, then put `metacareers.com` underneath
 * in caption-grey with a small outlined button. The reader's eyes never got to the
 * bottom. The visual weight was exactly inverted: the boards we had already
 * REJECTED looked like the answer and the answer looked like a footnote.
 *
 * So when nothing was confirmed (`lead`), this block is first, its headline says
 * plainly that no board was confirmed, the URL is set at reading size rather than
 * caption-grey (a person has to RECOGNISE `metacareers.com` as their employer's
 * site), and its action is a full-size contained button — the weight the rejected
 * boards used to hold. `CompanyCandidateList` renders below it, folded.
 *
 * It still says something useful when there is no URL to offer: a null `careersUrl`
 * is a decision, not an absence — no result's host named the company, and offering
 * the top-ranked stranger would spend a paid discovery run and one of the user's
 * monthly adds on somebody else's website. That case gets the same headline and
 * "paste the URL of their careers page", which is the one thing that moves it on.
 *
 * Presentational: the page owns the mutation, the flag, and which state we are in.
 */
export function CareersPageAnswer({
  query,
  careersUrl,
  unconfirmedCount,
  lead,
  onUse,
  busy,
}: CareersPageAnswerProps) {
  // A `const` copy purely so the null check narrows INSIDE the click handlers —
  // TypeScript drops a parameter's narrowing the moment it is captured by a
  // closure, and a `as string` cast is the thing this replaces.
  const url = careersUrl;

  if (!lead) {
    // Beside a confirmed board there is nothing to say unless we have a URL — the
    // boards above already are the answer.
    if (url === null) return null;
    // THE FOOTNOTE FORM, unchanged from what shipped. It is only reachable when the
    // server sends a `careersUrl` beside a board it DID confirm, which it does not do
    // today; it exists so that combination degrades to "one more option" rather than
    // to a second answer competing with the first.
    return (
      <Paper variant="outlined" sx={{ p: RESPONSIVE.spacing.paperPadding }}>
        <Typography variant="body2">Or use their careers page instead:</Typography>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
          <Typography variant="caption" sx={{ wordBreak: 'break-all' }}>
            {url}
          </Typography>
          <Button
            size="small"
            variant="outlined"
            disabled={busy}
            onClick={() => onUse(url)}
            aria-label={`Use this careers page for “${query}”`}
          >
            Use this
          </Button>
        </Stack>
      </Paper>
    );
  }

  return (
    // The answer arrives asynchronously and this is the actionable half of it, so
    // this block — not the folded list below — is the page's one polite live region.
    // `CompanyCandidateList` gives its own up while demoted for exactly this reason.
    <Paper
      variant="outlined"
      role="region"
      aria-live="polite"
      aria-label={url ? 'Careers page found' : 'No job board found'}
      data-testid="careers-page-answer"
      sx={{
        p: RESPONSIVE.spacing.paperPadding,
        // The one primary-bordered block on the page when there is something to
        // press. Without an action there is nothing to draw the eye TO, so the
        // ordinary border stays and the block reads as the verdict it is.
        ...(url ? { borderColor: 'primary.main' } : null),
      }}
    >
      <Stack spacing={1.5}>
        <Typography variant="subtitle1" component="h2">
          {unconfirmedCount === 0
            ? `No job board found for “${query}”`
            : `No board we can confirm belongs to “${query}”`}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {url
            ? 'Their careers page is the way in — we read it once and set the tracking up from there.'
            : 'Try pasting the URL of their careers page.'}
        </Typography>

        {url !== null ? (
          <>
            {/* READABLE, not caption-grey. Recognising the host as their employer's
                own site is the entire check a person can make here, and it cannot be
                made at 0.75rem in secondary text. `anywhere` so a long URL wraps
                instead of pushing the page sideways on a ~390px phone. */}
            <Typography
              variant="body1"
              sx={{ fontWeight: 500, overflowWrap: 'anywhere' }}
              data-testid="careers-page-url"
            >
              {url}
            </Typography>
            <Button
              variant="contained"
              disabled={busy}
              onClick={() => onUse(url)}
              // Names its subject, because "Use this careers page" on its own is
              // the same problem the row buttons have: a label that says nothing
              // about WHICH company it commits you to.
              aria-label={`Use this careers page for “${query}”`}
              // Full width on a phone (where a left-aligned button next to a
              // wrapped URL reads as a stray control), natural width from `sm` up.
              sx={{ alignSelf: { xs: 'stretch', sm: 'flex-start' } }}
            >
              Use this careers page
            </Button>
          </>
        ) : null}
      </Stack>
    </Paper>
  );
}
