import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';
import type { SearchCompanyResponse } from '../../features/userCompanies/userCompaniesApi';
import {
  buildNameSearchRows,
  narrateNameSearch,
  type NameSearchRow,
  type NameSearchStep,
} from './nameSearchNarration';
import {
  morphTimeline,
  statusDwell,
  ROW_FOLD_MS,
  ROW_IN_MS,
  ROW_MAX_HEIGHT,
  STATUS_FADE_MS,
  VERDICT_IN_MS,
  type MorphRowTiming,
} from './nameSearchMorph';

/**
 * WHY THIS IS A POST-HOC REVEAL AND NOT A LIVE FEED — read before adding a stage.
 *
 * `DiscoveryChecklist` and `DiscoveryNetworkLog` animate a 45-second backend job
 * polled every four seconds: their rungs tick over and their rows land three and
 * four at a time because that is genuinely when the news arrives. A name search is
 * ONE HTTP REQUEST THAT RETURNS IN ABOUT TWO SECONDS. There is no progress to watch.
 *
 * So this fakes nothing. There is exactly one moment it can honestly call in-flight
 * — the request — and it draws exactly one spinner for it, on the one line that is
 * really happening ("Searching the web for “Cisco”"). Everything after that is
 * already in the response when it lands: the query we sent, how many results came
 * back, WHICH results came back, how many resolved to a board, what the live probes
 * found. The morph below is REAL DATA REVEALED IN STAGES — every number and every
 * row is measured or returned server-side on this call — and only the order and the
 * beat between them are presentation. Nothing here is timed to look like work.
 *
 * A staged spinner pretending to watch each stage happen was the alternative, and
 * it is worse than no animation at all: this app's whole claim is that the UI states
 * what it actually knows — see the row-chip and "Last fetched" rules in
 * `src/frontend/CLAUDE.md` — and a progress bar over work that already finished is
 * the one lie that would cost that claim. If a later version wants the stages to
 * land as they truly happen, the fix is to make the endpoint stream them, never to
 * add a timer here.
 *
 * ── WHY IT IS A MORPHING LIST AND NOT SEVEN TICKS ────────────────────────────
 * It used to be seven stacked ✓ rungs describing what happened ("Asked the web for
 * X", "25 results came back", "Scored all 25…"). Rejected on sight: *"I don't like
 * how you have all these steps, it's really confusing. Just throw the request in
 * there, like we do the network request, and then merge them into one… It should be
 * this morphing list."*
 *
 * So the RESULTS themselves are the narration now. They land as rows, then fold away
 * in two passes — first everything that was not a board, then the boards whose token
 * does not name the company — and what is left standing is the answer. The seven
 * sentences were merged down to at most five and moved into one status line that
 * morphs alongside. Same row vocabulary as `DiscoveryNetworkLog` (a gutter, a
 * monospace URL, a right-hand verdict, the 260ms fade+rise, motion off under
 * `prefers-reduced-motion`) so this app has ONE language for "here is what we saw",
 * not two.
 *
 * THE ROWS ARE NEVER INVENTED. `trace.nonBoards` carries the real, server-redacted
 * URLs of the results that were not boards; `candidates` carries the boards with
 * their tokens and live counts; `careersUrl` is the answer. A backend that sends no
 * `nonBoards` gets a SHORTER list, not a filled-in one — the same rule the numbers
 * have always followed. The one row that stands for more than itself is
 * "…and N more results", and it says so.
 *
 * It leads INTO `CompanyCandidateList` / `CareersPageAnswer`, which are still the
 * answer surface, and it never gates them: they render the moment their data lands,
 * whatever this is doing above them. A single confident result auto-adds without any
 * list appearing, and this must not flash a narration on the way past — the page
 * unmounts it as soon as the add starts, so that path shows the one honest in-flight
 * line and then "Adding this company…".
 *
 * Presentational and flag-free, like the two discovery panels: the caller owns the
 * flag and owns the data.
 */

/**
 * The one place this component sets type in a monospace face, and it is the same job
 * `DiscoveryNetworkLog` uses it for: these are a machine's own record of what it
 * saw, and a proportional face makes a run of hostnames read as a sentence. Restated
 * rather than imported — that file's constant is private, and a shared module for
 * one string is not worth the indirection.
 */
const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

/**
 * THE WHOLE MORPH IS `animation-delay`, AND THERE ARE NO TIMERS AND NO STATE HERE.
 * `nameSearchMorph.ts` works out when every row arrives and leaves; this file turns
 * those numbers into CSS and does nothing else with them. See that module for why
 * a JS-driven version would be worse.
 *
 * `visibility` is in these keyframes on purpose. A row or a sentence that has left
 * is at `opacity: 0` but still in the accessibility tree, and a screen-reader user
 * would hear every discarded result and every superseded sentence read out after
 * the morph had finished. Ending on `hidden` (held by `forwards`) takes them out of
 * the tree at the same moment they leave the screen. It also interpolates the way
 * we need: an interval with a visible endpoint is visible throughout, so nothing
 * blinks out early.
 */
const KEYFRAMES = {
  '@keyframes nameSearchStatusIn': {
    from: { opacity: 0, visibility: 'hidden', transform: 'translateY(3px)' },
    to: { opacity: 1, visibility: 'visible', transform: 'none' },
  },
  '@keyframes nameSearchStatusOut': {
    from: { opacity: 1 },
    to: { opacity: 0, visibility: 'hidden' },
  },
  '@keyframes nameSearchRowIn': {
    from: { opacity: 0, transform: 'translateY(-3px)' },
    to: { opacity: 1, transform: 'none' },
  },
  '@keyframes nameSearchRowGrow': {
    from: {
      opacity: 0,
      visibility: 'hidden',
      maxHeight: 0,
      paddingTop: 0,
      paddingBottom: 0,
      marginBottom: 0,
    },
    to: {
      opacity: 1,
      visibility: 'visible',
      maxHeight: ROW_MAX_HEIGHT,
      paddingTop: '4px',
      paddingBottom: '4px',
      marginBottom: '2px',
    },
  },
  '@keyframes nameSearchRowOut': {
    from: { opacity: 1, maxHeight: ROW_MAX_HEIGHT },
    to: {
      opacity: 0,
      visibility: 'hidden',
      maxHeight: 0,
      paddingTop: 0,
      paddingBottom: 0,
      marginBottom: 0,
      transform: 'translateY(-4px)',
    },
  },
  '@keyframes nameSearchVerdictIn': {
    from: { opacity: 0 },
    to: { opacity: 1 },
  },
} as const;

/**
 * One state of the status line.
 *
 * All of them share a single grid cell, so the block is as tall as the tallest
 * sentence and nothing below it moves as they cross-fade. Under reduced motion they
 * would all be painted on top of each other, so that case shows the LAST one — the
 * end state, which is the same thing the rows do.
 */
function statusAnimation(index: number, dwellMs: number, last: boolean) {
  const inAt = index * dwellMs;
  return {
    ...KEYFRAMES,
    gridArea: '1 / 1',
    animation: last
      ? `nameSearchStatusIn ${STATUS_FADE_MS}ms ease-out ${inAt}ms both`
      : `nameSearchStatusIn ${STATUS_FADE_MS}ms ease-out ${inAt}ms backwards, ` +
        `nameSearchStatusOut ${STATUS_FADE_MS}ms ease-in ${inAt + dwellMs}ms forwards`,
    '@media (prefers-reduced-motion: reduce)': {
      animation: 'none',
      display: last ? 'block' : 'none',
    },
  } as const;
}

/**
 * One row's arrival and its departure, as one `animation` list.
 *
 * The two never overlap in time and neither fills into the other's window, so the
 * shared `opacity` is unambiguous: `backwards` holds the row invisible until it
 * lands, nothing fills between the two, and `forwards` holds it collapsed once it
 * has gone. Under reduced motion a row that folds is simply not there — the reader
 * gets the END STATE (the answer), which is the point of the morph, rather than
 * every row at once.
 */
function rowAnimation(timing: MorphRowTiming) {
  const arrival = timing.late ? 'nameSearchRowGrow' : 'nameSearchRowIn';
  const parts = [`${arrival} ${ROW_IN_MS}ms ease-out ${timing.inAt}ms backwards`];
  if (timing.outAt !== null) {
    parts.push(
      `nameSearchRowOut ${ROW_FOLD_MS}ms cubic-bezier(0.4, 0, 0.2, 1) ${timing.outAt}ms forwards`
    );
  }
  return {
    ...KEYFRAMES,
    // Load-bearing with the collapse: it is what makes `maxHeight` clip rather than
    // spill. Harmless once the animation is over, when the row has no `maxHeight`
    // at all and sizes to its own content.
    overflow: 'hidden',
    animation: parts.join(', '),
    '@media (prefers-reduced-motion: reduce)': {
      animation: 'none',
      ...(timing.outAt !== null ? { display: 'none' } : null),
    },
  } as const;
}

/** The verdict on a board, revealed as the list reaches it rather than up front. */
function verdictAnimation(delayMs: number) {
  return {
    ...KEYFRAMES,
    animation: `nameSearchVerdictIn ${VERDICT_IN_MS}ms ease-out ${delayMs}ms backwards`,
    '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
  } as const;
}

/** Colour only where it means something — the same rule the network log follows. */
function statusColor(kind: NameSearchRow['kind']): string {
  if (kind === 'answer') return 'success.main';
  if (kind === 'rejected') return 'warning.main';
  return 'text.secondary';
}

function StatusLine({
  step,
  index,
  dwellMs,
  last,
}: {
  step: NameSearchStep;
  index: number;
  dwellMs: number;
  last: boolean;
}) {
  return (
    <Box data-testid={`name-search-step-${step.key}`} sx={statusAnimation(index, dwellMs, last)}>
      <Stack direction="row" spacing={1} alignItems="center">
        {/* The one honest in-flight moment, and the only spinner in the panel.
            There is no ✓ opposite it: by the time any other sentence is on screen
            every stage it could tick has already happened, and a tick per line
            would be the seven-rung stack coming back one glyph at a time. */}
        {step.active ? <CircularProgress size={12} aria-label="in progress" /> : null}
        <Typography variant="body2" sx={{ fontWeight: step.active ? 600 : 400 }}>
          {step.label}
        </Typography>
      </Stack>
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
  );
}

/**
 * One result. Two lines at most, never a table.
 *
 * A table would need a column for the URL, and a URL is the one field here with no
 * bounded width — so on a narrow screen it either truncates (deleting the part the
 * reader recognises the result by) or pushes the page sideways. Same shape as
 * `DiscoveryNetworkLog`'s request row for the same reason.
 */
function ResultRow({
  row,
  timing,
  verdictAt,
}: {
  row: NameSearchRow;
  timing: MorphRowTiming;
  verdictAt: number;
}) {
  const answer = row.kind === 'answer';
  // A board's verdict arrives as the list gets to it. The careers page's does not:
  // that row IS the verdict, and it only appears once everything else has gone.
  const lateVerdict = row.meta !== null;
  return (
    <Box
      component="li"
      data-testid="name-search-row"
      data-kind={row.kind}
      sx={{
        ...rowAnimation(timing),
        listStyle: 'none',
        paddingTop: '4px',
        paddingBottom: '4px',
        marginBottom: '2px',
        pl: 1,
        // The ONE accent in the panel, spent on the thing that survives the morph.
        borderLeft: 2,
        borderColor: answer ? 'success.main' : 'transparent',
        bgcolor: answer ? 'action.selected' : 'transparent',
        borderRadius: answer ? '0 4px 4px 0' : 0,
      }}
    >
      <Stack direction="row" spacing={1} alignItems="baseline">
        <Typography
          component="span"
          aria-hidden
          sx={{
            fontFamily: MONO,
            fontSize: '0.7rem',
            color: 'text.secondary',
            flexShrink: 0,
            width: 20,
            textAlign: 'right',
          }}
        >
          {row.rank}
        </Typography>
        <Typography
          component="span"
          sx={{
            fontFamily: MONO,
            fontSize: '0.7rem',
            minWidth: 0,
            flexGrow: 1,
            overflowWrap: 'anywhere',
            color: answer ? 'text.primary' : 'text.secondary',
            fontWeight: answer ? 600 : 400,
          }}
        >
          {row.url}
        </Typography>
        <Typography
          component="span"
          data-testid="name-search-row-status"
          sx={{
            fontSize: '0.65rem',
            fontWeight: 700,
            letterSpacing: '0.03em',
            whiteSpace: 'nowrap',
            flexShrink: 0,
            color: statusColor(row.kind),
            ...(lateVerdict ? verdictAnimation(verdictAt) : null),
          }}
        >
          {row.status}
        </Typography>
      </Stack>
      {row.meta ? (
        // NEVER OMITTED FOR A BOARD. The name path's worst failure is tracking a
        // stranger's live board — searching "Databricks" returns Guidehouse's, with
        // 794 real jobs — and the token plus the count is the only thing a person
        // can catch that with.
        <Typography
          variant="caption"
          data-testid="name-search-row-meta"
          sx={{ display: 'block', pl: '28px', color: 'text.secondary' }}
        >
          {row.meta}
        </Typography>
      ) : null}
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
 * The name search, narrated as one list that narrows to its answer. See the file
 * header for why this is a reveal, not a feed.
 *
 * Deliberately NOT a live region. `CareersPageAnswer` / `CompanyCandidateList`
 * below own `aria-live`, because they are the actionable answer, and a second
 * polite region firing at the same instant — repeatedly, as this one morphs — would
 * talk over the question the user actually has to answer. What is on screen at any
 * moment stays readable in document order for anyone who wants it.
 */
export function NameSearchProgress({ query, searching, result }: NameSearchProgressProps) {
  // Nothing has been searched for, or the answer has been cleared. Either way there
  // is no run to narrate, and a panel that outlives its subject is the stale-question
  // failure `MyCompaniesPage` clears its state so carefully to avoid.
  if (query === null || (!searching && result === null)) {
    return null;
  }
  // `searching ? null : result` rather than trusting `result`: a second search leaves
  // the previous answer in place for the render before the page clears it, and
  // narrating the old numbers under a spinner for the new name would be the one thing
  // this component exists not to do.
  const landed = searching ? null : result;
  const steps = narrateNameSearch(query, landed);
  const rows = landed === null ? [] : buildNameSearchRows(landed);
  const timeline = morphTimeline(rows);
  const dwellMs = statusDwell(timeline.totalMs, steps.length);

  return (
    <Paper
      variant="outlined"
      sx={{ p: RESPONSIVE.spacing.paperPadding, bgcolor: 'action.hover' }}
      data-testid="name-search-progress"
    >
      {/* One grid cell holding every sentence, so the block is as tall as the
          tallest of them and nothing below it jumps as they cross-fade. */}
      <Box sx={{ display: 'grid' }}>
        {steps.map((step, index) => (
          <StatusLine
            key={step.key}
            step={step}
            index={index}
            dwellMs={dwellMs}
            last={index === steps.length - 1}
          />
        ))}
      </Box>
      {rows.length > 0 ? (
        <Box
          component="ul"
          data-testid="name-search-rows"
          sx={{ listStyle: 'none', m: 0, mt: 1, p: 0 }}
        >
          {rows.map((row, index) => (
            <ResultRow
              key={row.key}
              row={row}
              timing={timeline.rows[index]}
              verdictAt={timeline.verdictAt}
            />
          ))}
        </Box>
      ) : null}
    </Paper>
  );
}
