import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';
import type { SearchCompanyResponse } from '../../features/userCompanies/userCompaniesApi';
import { narrateNameSearch, type NameSearchStep } from './nameSearchNarration';

/**
 * WHY THIS IS A POST-HOC REVEAL AND NOT A LIVE FEED — read before adding a stage.
 *
 * `DiscoveryChecklist` and `DiscoveryNetworkLog` animate a 45-second backend job polled
 * every four seconds: their rungs tick over and their rows land three and four at a time
 * because that is genuinely when the news arrives. A name search is ONE HTTP REQUEST
 * THAT RETURNS IN ABOUT TWO SECONDS. There is no progress to watch.
 *
 * So this fakes nothing. There is exactly one moment it can honestly call in-flight —
 * the request — and it draws exactly one spinner for it, on the one step that is really
 * happening ("Searching the web for “Cisco”"). Everything after that is already in the
 * response when it lands: the query we sent, how many results came back, how many were
 * dropped, how many resolved to a board, what the live probes found. Those steps are
 * REAL DATA REVEALED IN STAGES — every number is measured server-side on this call
 * (`SearchTrace`), and only the order and the beat between them are presentation.
 * Nothing here is timed to look like work.
 *
 * A staged spinner pretending to watch each stage happen was the alternative, and it is
 * worse than no animation at all: this app's whole claim is that the UI states what it
 * actually knows — see the row-chip and "Last fetched" rules in `src/frontend/CLAUDE.md`
 * — and a progress bar over work that already finished is the one lie that would cost
 * that claim. If a later version wants the steps to land as they truly happen, the fix
 * is to make the endpoint stream them, never to add a timer here.
 *
 * The stages are worth showing because they ARE the feature's argument. The search
 * engine is only asked to enumerate URLs; which of them is a real board is decided by
 * our own free deterministic matcher over all 25 results, and measured, the right board
 * is the top result only about half the time. "Scored all 19 ourselves" is the sentence
 * that explains why typing a name works at all.
 *
 * It leads INTO `CompanyCandidateList`, which is still the answer surface, and it never
 * gates it: the list renders the moment its data lands, whatever this is doing above it.
 * A single confident result auto-adds without any list appearing, and this must not
 * flash a narration on the way past — the page unmounts it as soon as the add starts, so
 * that path shows the one honest in-flight step and then "Adding this company…".
 *
 * Presentational and flag-free, like the two discovery panels: the caller owns the flag
 * and owns the data.
 */

/**
 * The one place this component sets type in a monospace face, and it is the same job
 * `DiscoveryNetworkLog` uses it for: the query is a machine's own input, not prose, and
 * a proportional face makes a run of hostnames read as a sentence. Restated rather than
 * imported — that file's constant is private, and a shared module for one string is not
 * worth the indirection.
 */
const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

/**
 * A step arriving — the same 260ms fade+rise `DiscoveryNetworkLog` gives an arriving
 * request row, for the same reason: it reads as arrival rather than as the layout
 * glitching. CSS rather than a React transition because it must fire on MOUNT and never
 * again, so the in-flight step keeps its DOM node when the answer lands and does not
 * replay itself while the steps below it come in.
 *
 * NO TIMERS AND NO STATE, which is what keeps this component pure. A JS-driven reveal
 * would need a run counter to reset on a second search, a `setState` from a `setTimeout`
 * on every beat, and it would be the only thing on this page still animating after the
 * test that rendered it had finished.
 *
 * `backwards` fill is load-bearing with the delay: without it every step paints at full
 * opacity on mount and then re-fades from zero when its delay elapses, which is exactly
 * the flash the stagger exists to remove. With it the rows hold their space — so nothing
 * reflows down the page — and only the ink arrives.
 */
const STEP_ANIMATION_MS = 260;
const STEP_STAGGER_MS = 220;

function stepAnimation(index: number) {
  return {
    '@keyframes nameSearchStepIn': {
      from: { opacity: 0, transform: 'translateY(-3px)' },
      to: { opacity: 1, transform: 'none' },
    },
    animation: `nameSearchStepIn ${STEP_ANIMATION_MS}ms ease-out ${
      index * STEP_STAGGER_MS
    }ms backwards`,
    '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
  } as const;
}

function StepRow({ step, index }: { step: NameSearchStep; index: number }) {
  return (
    <Box
      component="li"
      data-testid={`name-search-step-${step.key}`}
      sx={{ ...stepAnimation(index), listStyle: 'none', display: 'flex', gap: 1, py: 0.25 }}
    >
      {/* The same glyph gutter and the same ✓ / spinner vocabulary as
          `DiscoveryChecklist`'s rungs, so the two panels read as one system. There is
          no ○ here on purpose: a pending circle is a claim that a step has not happened
          yet, and by the time any of these render, every one of them has. */}
      <Box sx={{ width: 20, flexShrink: 0, textAlign: 'center', lineHeight: '1.5rem' }}>
        {step.active ? (
          <CircularProgress size={12} aria-label="in progress" />
        ) : (
          <Typography component="span" color="success.main">
            ✓
          </Typography>
        )}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: step.active ? 600 : 400 }}>
          {step.label}
        </Typography>
        {step.detail ? (
          <Typography
            variant="caption"
            color="text.secondary"
            data-testid={`name-search-detail-${step.key}`}
            sx={{
              display: 'block',
              // `anywhere`, because the query is one unbroken 78-character run of
              // hostnames: the page itself must never scroll sideways, so this wraps
              // rather than pushing its container wide on a phone.
              overflowWrap: 'anywhere',
              ...(step.mono ? { fontFamily: MONO, fontSize: '0.7rem' } : null),
            }}
          >
            {step.detail}
          </Typography>
        ) : null}
      </Box>
    </Box>
  );
}

interface NameSearchProgressProps {
  /** What the user typed. Null when no name search is in play this session. */
  query: string | null;
  /** The request is genuinely out. The one state that draws a spinner. */
  searching: boolean;
  /** The landed response, or null while it is still out. */
  result: SearchCompanyResponse | null;
}

/**
 * The name search, narrated. See the file header for why this is a reveal, not a feed.
 *
 * Deliberately NOT a live region. `CompanyCandidateList` below is the `aria-live`
 * region, because it is the actionable answer, and a second polite region firing at the
 * same instant — twice, since this one grows from one step to five — would talk over the
 * question the user actually has to answer. The steps stay readable in document order
 * for anyone who wants them.
 */
export function NameSearchProgress({ query, searching, result }: NameSearchProgressProps) {
  // Nothing has been searched for, or the answer has been cleared. Either way there is
  // no run to narrate, and a panel that outlives its subject is the stale-question
  // failure `MyCompaniesPage` clears its state so carefully to avoid.
  if (query === null || (!searching && result === null)) {
    return null;
  }
  // `searching ? null : result` rather than trusting `result`: a second search leaves
  // the previous answer in place for the render before the page clears it, and narrating
  // the old numbers under a spinner for the new name would be the one thing this
  // component exists not to do.
  const steps = narrateNameSearch(query, searching ? null : result);

  return (
    <Paper
      variant="outlined"
      sx={{ p: RESPONSIVE.spacing.paperPadding, bgcolor: 'action.hover' }}
      data-testid="name-search-progress"
    >
      <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
        {steps.map((step, index) => (
          <StepRow key={step.key} step={step} index={index} />
        ))}
      </Box>
    </Paper>
  );
}
