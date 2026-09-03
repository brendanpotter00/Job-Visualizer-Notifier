import { useEffect, useState } from 'react';
import Box from '@mui/material/Box';
import ButtonBase from '@mui/material/ButtonBase';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type {
  DiscoveryPayloadSample,
  DiscoveryRequest,
  UserCompany,
} from '../../features/userCompanies/userCompaniesApi';
import {
  chosenDiscoveryRequest,
  describeNetworkSummary,
  formatByteSize,
  resolveDiscoveryOutcome,
} from './companyHealth';

/**
 * The one place this app sets type in a monospace face, and it is doing a job: these
 * rows are a machine's own record of what it saw, and a proportional face makes a URL
 * and a status code read as prose. Aligned digits are also what lets the status column
 * scan vertically without a table (which would need horizontal scroll on a phone).
 */
const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

/**
 * A row arriving is the ONE thing worth animating here.
 *
 * The panel narrates something that is genuinely happening a few hundred milliseconds
 * at a time, and the list poll is 4s — so rows land in batches of three or four. Without
 * motion that reads as the layout glitching; with a short fade+rise it reads as arrival,
 * which is the true thing. CSS animation rather than a React transition because it must
 * fire on MOUNT and never again: a re-render from the next poll keeps the same DOM node
 * and therefore never replays, so only genuinely new rows move.
 *
 * The one other time it fires is "show all N", where the also-rans mount for the first
 * time. That reads as a reveal rather than a lie about when they arrived — and the row
 * the user was already looking at, the picked one, keeps its DOM node and stays still.
 */
const ROW_ANIMATION = {
  '@keyframes discoveryRequestIn': {
    from: { opacity: 0, transform: 'translateY(-3px)' },
    to: { opacity: 1, transform: 'none' },
  },
  animation: 'discoveryRequestIn 260ms ease-out',
  '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
} as const;

/**
 * ...and the one worth animating on the way OUT: the moment the search ends.
 *
 * The narrowing is the single most legible thing this panel does — fourteen rows become
 * one — and it used to happen between two frames, which reads as the list glitching
 * rather than as an answer being found. The also-rans now collapse FROM THE OUTSIDE IN
 * (`collapseDelayFor`), so the list closes toward the row that survives and the eye is
 * pulled to it instead of having to re-find it.
 *
 * ONLY THE AUTOMATIC NARROWING ANIMATES. When the user presses "show just the one we
 * picked" the rows go instantly, deliberately: a deliberate click that takes 600ms to
 * obey feels slow, and there is nothing to point at — they already know which row they
 * want. The distinction is `collapsing`, which is set from an effect when a winner
 * FIRST APPEARS while mounted, and never by the toggle.
 *
 * `maxHeight` is a ceiling rather than a measured height (we do not measure rows — that
 * would mean a layout read per row per poll). 96px comfortably covers the three-line
 * chosen row and the two-line ordinary one; a row taller than that clips its last few
 * pixels at the very start of a fade it is already losing, which is not perceptible.
 */
const ROW_COLLAPSE_MS = 340;
const ROW_COLLAPSE_STAGGER_MS = 22;

function rowCollapse(delayMs: number) {
  return {
    overflow: 'hidden',
    '@keyframes discoveryRequestOut': {
      from: { opacity: 1, maxHeight: '96px', paddingTop: '4px', paddingBottom: '4px' },
      to: {
        opacity: 0,
        maxHeight: 0,
        paddingTop: 0,
        paddingBottom: 0,
        transform: 'translateY(-4px)',
      },
    },
    // `both` so the row HOLDS its collapsed end state for the frames between the
    // animation ending and React dropping the node.
    animation: `discoveryRequestOut ${ROW_COLLAPSE_MS}ms cubic-bezier(0.4, 0, 0.2, 1) ${delayMs}ms both`,
    // Reduced motion gets the old behaviour exactly: the rows are simply not there.
    '@media (prefers-reduced-motion: reduce)': { animation: 'none', display: 'none' },
  } as const;
}

/**
 * How long a row waits before it goes: the FARTHEST from the winner leaves first, so the
 * list zips shut inward rather than top-down. Distance-based rather than index-based
 * because the winner is rarely the first row.
 */
function collapseDelayFor(index: number, chosenIndex: number, total: number): number {
  const farthest = Math.max(chosenIndex, total - 1 - chosenIndex);
  const distance = Math.abs(index - chosenIndex);
  return (farthest - distance) * ROW_COLLAPSE_STAGGER_MS;
}

/** The whole collapse, end to end — what the effect waits before dropping the rows. */
function collapseWindowMs(total: number, chosenIndex: number): number {
  return ROW_COLLAPSE_MS + Math.max(chosenIndex, total - 1 - chosenIndex) * ROW_COLLAPSE_STAGGER_MS;
}

/** The "we are still listening" dot. Same rule: motion only where something is moving. */
const PULSE = {
  '@keyframes discoveryListening': {
    '0%, 100%': { opacity: 0.25 },
    '50%': { opacity: 1 },
  },
  animation: 'discoveryListening 1.4s ease-in-out infinite',
  '@media (prefers-reduced-motion: reduce)': { animation: 'none', opacity: 0.6 },
} as const;

/**
 * MUI colour slot for an HTTP status — and it stays GREY for a 200.
 *
 * Colouring every successful row green would spend the panel's one accent forty times
 * over and leave nothing to mark the request we actually picked. A board's own 4xx is
 * genuinely worth an eye (it is often why the feed is missing), so that is where the
 * colour goes; the ordinary case is meant to recede.
 */
function statusColor(status: number): string {
  if (status >= 400) return 'error.main';
  if (status && (status < 200 || status >= 300)) return 'warning.main';
  return 'text.secondary';
}

/** ...and the same rule for the detail line: colour only where something is wrong. */
function detailColor(state: DiscoveryRequest['state']): string {
  return state === 'oversize' || state === 'blocked' ? 'warning.main' : 'text.secondary';
}

/**
 * The second line of a row: what this response weighed and what was in it.
 *
 * `records === null` is NOT the same as `0` and the copy keeps them apart. Null means
 * the pre-filter has not reached this response yet (it only runs once the browser
 * closes), so during the capture every row honestly says nothing about its contents;
 * zero means we opened it and there were no job postings in it, which is the entire
 * evidence for the commonest refusal we serve.
 */
function describeRequest(request: DiscoveryRequest): string {
  const size = formatByteSize(request.bytes);
  if (request.state === 'oversize') {
    return `${size} — bigger than we can read in one go`;
  }
  if (request.state === 'blocked') {
    return `${size} — ${request.note ?? 'we refuse to fetch this address'}`;
  }
  if (request.records === null) {
    return size;
  }
  if (request.records === 0) {
    return `${size} — no job postings in it`;
  }
  return `${size} — ${request.records.toLocaleString()} job postings`;
}

/**
 * The payload sample — the answer to "what IS a job, underneath".
 *
 * IT HAS A NAME NOW. It used to open on "One of the 88 records it sent back", which
 * describes our plumbing (a record, from a response) rather than the thing a reader is
 * looking at (a job, as the board actually stores it). The heading says what it is; the
 * line under it keeps the provenance, which is the supporting fact rather than the point.
 *
 * AND IT NO LONGER SCROLLS. It sat in a 220px `overflow: auto` box, so the single most
 * interesting artifact on the page was delivered four lines at a time through a letterbox
 * — inside a list row, where a nested scroll region is also the thing that steals the
 * page's own scroll. Full height instead. That is only safe because the text is CLIPPED
 * SERVER-SIDE (`progress.py::_MAX_SAMPLE_CHARS`) before it is ever sent, so this cannot
 * grow without bound however verbose a board's JSON is; if that clip is ever loosened,
 * this is the box that has to grow a ceiling again.
 *
 * `pre-wrap` + `break-word` rather than `pre` + horizontal scroll: a nested scroll
 * region that only scrolls sideways is close to undiscoverable on a phone, and this
 * panel lives inside a list row. The page itself must never scroll sideways, which is
 * the constraint that decides this — nothing here can be wider than its container.
 */
function PayloadSample({ sample }: { sample: DiscoveryPayloadSample }) {
  return (
    <Box sx={{ mt: 1 }} data-testid="discovery-payload-sample">
      <Typography variant="subtitle2" component="p" sx={{ mb: 0.25 }}>
        What one job looks like under the hood
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
        One of the {sample.records.toLocaleString()} records it sent back
        {sample.path ? (
          <>
            , from{' '}
            <Box component="span" sx={{ fontFamily: MONO }}>
              {sample.path}
            </Box>
          </>
        ) : null}
      </Typography>
      <Box
        component="pre"
        sx={{
          m: 0,
          mt: 0.5,
          p: 1.5,
          bgcolor: 'background.paper',
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          fontFamily: MONO,
          fontSize: '0.8rem',
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {sample.text}
      </Box>
    </Box>
  );
}

/**
 * One request. Two lines, never a table.
 *
 * A table would need a column for the URL, and a URL is the one field here with no
 * bounded width — so on a narrow screen it either truncates (deleting the part the
 * reader recognises the endpoint by) or pushes the page sideways. Two lines with the
 * verb and status in a fixed gutter keeps the same vertical scan a table buys, wraps
 * instead of overflowing, and leaves the second line free for the meaning.
 */
function RequestRow({
  request,
  collapsing = false,
  collapseDelayMs = 0,
}: {
  request: DiscoveryRequest;
  /** This row is on its way out because a winner was just picked. See `rowCollapse`. */
  collapsing?: boolean;
  /** Its place in the outside-in stagger. Meaningless unless `collapsing`. */
  collapseDelayMs?: number;
}) {
  const chosen = request.state === 'chosen';
  return (
    <Box
      component="li"
      data-testid="discovery-request"
      data-state={request.state}
      sx={{
        ...ROW_ANIMATION,
        listStyle: 'none',
        py: 0.5,
        pl: 1,
        // The ONE accent in the panel, spent on the one thing the user asked for: which
        // request did you pick. Everything else stays quiet so this reads at a glance.
        borderLeft: 2,
        borderColor: chosen ? 'success.main' : 'transparent',
        bgcolor: chosen ? 'action.selected' : 'transparent',
        borderRadius: chosen ? '0 4px 4px 0' : 0,
        // LAST, so it wins over the entrance animation above: a row that is leaving
        // must never be told to play its arrival again.
        ...(collapsing ? rowCollapse(collapseDelayMs) : null),
      }}
    >
      <Stack direction="row" spacing={1} alignItems="baseline">
        <Typography
          component="span"
          sx={{
            fontFamily: MONO,
            fontSize: '0.7rem',
            color: statusColor(request.status),
            flexShrink: 0,
            width: 62,
          }}
        >
          {request.method} {request.status || '—'}
        </Typography>
        <Typography
          component="span"
          sx={{
            fontFamily: MONO,
            fontSize: '0.7rem',
            minWidth: 0,
            overflowWrap: 'anywhere',
            color: chosen ? 'text.primary' : 'text.secondary',
            fontWeight: chosen ? 600 : 400,
          }}
        >
          {request.url}
        </Typography>
        {chosen ? (
          <Chip
            label="Picked"
            size="small"
            color="success"
            variant="outlined"
            sx={{ height: 18, flexShrink: 0, '& .MuiChip-label': { px: 0.75, fontSize: '0.65rem' } }}
          />
        ) : null}
      </Stack>
      <Typography
        variant="caption"
        sx={{ display: 'block', pl: '70px', color: detailColor(request.state) }}
        data-testid="discovery-request-detail"
      >
        {describeRequest(request)}
      </Typography>
      {chosen && request.note ? (
        // Deliberately NOT green. The border, the tinted ground and the chip have
        // already said "this is the one"; a fourth accent on the same row spends the
        // panel's one colour four times and leaves the eye nowhere to land.
        <Typography variant="caption" sx={{ display: 'block', pl: '70px', color: 'text.secondary' }}>
          {request.note}
        </Typography>
      ) : null}
    </Box>
  );
}

interface DiscoveryNetworkLogProps {
  company: UserCompany;
}

/**
 * "Show me what you're actually doing" — the evidence, under the live view.
 *
 * OPEN BY DEFAULT, AND IT NARROWS. Those are one decision, not two. It used to be
 * collapsed in every state, on the reasoning that the checklist above had just been cut
 * from ~14 lines to ~8 for being busy and forty unfurled rows would undo that. What
 * that reasoning missed is that a collapsed log has no streaming in it: rows landing
 * three and four at a time is the only part of a one-time setup a person can actually
 * watch, and it was happening inside a closed box.
 *
 * The narrowing is what pays for opening it. While the capture runs the list is long
 * because that is the point — this is the machine's own record arriving. The moment a
 * request is PICKED the list becomes that one row plus the JSON it returned, so the
 * state a user is left staring at (every settled row, forever, on a partial board) is
 * two lines and a payload — calmer than the eight-line checklist it hangs under, and
 * far calmer than the fourteen rows that used to be one click away.
 *
 * THE DISCARDED ROWS ARE NOT THROWN AWAY, they are one caption-sized link away — "Show
 * the other 13 requests". They answer exactly one question, and it is a real one on a
 * partial board: why did you pick THAT one and not the endpoint I can see in my own
 * devtools. The heading keeps counting them ("14 requests · 1 picked"), so the link is
 * never the only thing left saying they existed. It counts what SURVIVED the size
 * budget, which is what it can actually show.
 *
 * A REFUSAL HAS NO WINNER, so nothing narrows and the whole list stays — that case is
 * the reason the panel exists. "None of the 14 JSON requests this page made returned a
 * list of job postings" is an assertion; the fourteen rows are the evidence for it.
 *
 * It renders NOTHING when nothing was recorded. That is not an omission: a page that
 * fetched no JSON at all (measured: metacareers.com) has no evidence to show, the ✕ on
 * the checklist already says so in the user's own words, and a second component
 * restating it is exactly the say-it-four-times problem this panel was cut back from.
 *
 * Presentational and flag-free, like `DiscoveryChecklist` around it — the caller owns
 * the feature flag, and the data rides the list poll the page already runs.
 */
export function DiscoveryNetworkLog({ company }: DiscoveryNetworkLogProps) {
  const requests = company.discovery?.network?.requests ?? [];
  const summary = describeNetworkSummary(company);
  // Keyed on the winner EXISTING, not on the run being over: `choose_request` is written
  // during `verify_read`, one publish before the terminal write, so narrowing on the
  // outcome would leave a settled answer looking like an open search for a poll longer.
  //
  // `indexOf` off the SAME object the exported predicate returned, rather than a second
  // `.find`: the panel and its heading must never disagree about which row won, which is
  // the whole reason `chosenDiscoveryRequest` is exported at all.
  const chosen = chosenDiscoveryRequest(company);
  const hasWinner = chosen !== null;
  const chosenIndex = chosen ? requests.indexOf(chosen) : -1;

  const [open, setOpen] = useState(true);
  const [showAll, setShowAll] = useState(false);
  // "The also-rans are gone for good."
  //
  // SEEDED FROM THE MOUNT-TIME WINNER, which is the whole trick. A settled row arrives
  // with its winner already chosen and must render as ONE row on the very first frame:
  // there is no search to watch end, and playing the collapse there would be a lie about
  // when it happened (and would animate on every remount, forever). A row that is still
  // searching mounts `false`, so its rows are still on screen — and therefore still
  // animatable — at the moment the winner lands.
  //
  // It only ever goes false -> true, and that is also what keeps the write out of the
  // effect BODY. `react-hooks/set-state-in-effect` forbids the synchronous form and is
  // right to: the synchronous version rendered one frame with the rows already dropped
  // and then brought them back in order to animate them away, which is a visible flash.
  // Here the effect only ARMS a timer and the timer's callback does the write.
  const [narrowSettled, setNarrowSettled] = useState(hasWinner);

  useEffect(() => {
    if (!hasWinner || narrowSettled) {
      return undefined;
    }
    const timer = setTimeout(
      () => setNarrowSettled(true),
      collapseWindowMs(requests.length, chosenIndex),
    );
    return () => clearTimeout(timer);
  }, [hasWinner, narrowSettled, requests.length, chosenIndex]);

  if (requests.length === 0 || summary === null) {
    return null;
  }
  const running = resolveDiscoveryOutcome(company) === 'running';
  const sample = company.discovery?.network?.sample ?? null;
  const narrowed = hasWinner && !showAll;
  // The collapse window: we are narrowed, but the rows being dropped have not been
  // dropped yet. Pressing "show the other 13" mid-collapse clears `narrowed`, so the
  // toggle always wins and the rows it brings back are never animating themselves away.
  // After the window closes this is false forever, which is what keeps the MANUAL
  // toggle instant in both directions — see `rowCollapse`.
  const leaving = narrowed && !narrowSettled;
  const alsoRans = requests.length - 1;

  return (
    <Box sx={{ mt: 1.5 }} data-testid="discovery-network">
      <ButtonBase
        onClick={() => setOpen((isOpen) => !isOpen)}
        // `aria-expanded` alone: the disclosure pattern does not require
        // `aria-controls`, and pointing it at an unmounted list would be a lie.
        aria-expanded={open}
        data-testid="discovery-network-toggle"
        sx={{
          width: '100%',
          justifyContent: 'flex-start',
          borderRadius: 1,
          px: 0.5,
          py: 0.25,
          textAlign: 'left',
        }}
      >
        <Typography
          component="span"
          sx={{ mr: 0.75, color: 'text.secondary', fontSize: '0.7rem', lineHeight: 1.8 }}
          aria-hidden
        >
          {open ? '▾' : '▸'}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {summary}
        </Typography>
        {running ? (
          <Box
            aria-hidden
            sx={{
              ...PULSE,
              ml: 0.75,
              width: 6,
              height: 6,
              borderRadius: '50%',
              bgcolor: 'info.main',
              flexShrink: 0,
              alignSelf: 'center',
            }}
          />
        ) : null}
      </ButtonBase>

      {/* `unmountOnExit`: a log the user has PUT AWAY is nothing, not forty hidden list
          items per row. It opens by default, so this now matters most for the row a user
          deliberately closed — and for the refused boards, which are the only ones that
          still render a long list once they settle. */}
      <Collapse in={open} unmountOnExit>
        <Box
          component="ul"
          data-testid="discovery-request-list"
          data-narrowed={narrowed ? 'true' : 'false'}
          sx={{ listStyle: 'none', m: 0, mt: 0.5, p: 0 }}
        >
          {requests.map((request, index) => {
            // The FULL list is mapped and the also-rans are dropped here rather than
            // filtered upstream, so `index` stays the row's position in the capture. That
            // is what keeps the picked row's DOM node identical across "show all" — key
            // it by position-within-the-visible-list instead and the one row the user is
            // reading remounts and replays its arrival animation on every toggle.
            //
            // Index keys at all because this list is append-only in arrival order, so the
            // index IS the row's identity. Keying on the URL would remount every row of a
            // board that fetches the same endpoint twice.
            const alsoRan = request.state !== 'chosen';
            // Held one collapse longer than the narrowing itself, so the rows we are
            // dropping are still there to be animated out. Once `leaving` clears they go
            // the way they always did: not rendered at all.
            if (narrowed && alsoRan && !leaving) {
              return null;
            }
            return (
              <RequestRow
                key={index}
                request={request}
                collapsing={leaving && alsoRan}
                collapseDelayMs={
                  leaving && alsoRan
                    ? collapseDelayFor(index, chosenIndex, requests.length)
                    : 0
                }
              />
            );
          })}
        </Box>
        {/* The payload belongs to the picked row, so it sits directly under the list —
            which in the narrowed state means directly under the one row it came from. */}
        {sample ? <PayloadSample sample={sample} /> : null}
        {/* LAST, and caption-sized. The winner and its JSON are the answer; this is the
            footnote for the one person who wants to argue with it. Rendered only when
            there is genuinely something behind it — a board whose only recorded request
            IS the winner has no "others" to show. */}
        {alsoRans > 0 && hasWinner ? (
          <Link
            component="button"
            type="button"
            variant="caption"
            underline="hover"
            color="text.secondary"
            onClick={() => setShowAll((isShown) => !isShown)}
            aria-expanded={showAll}
            data-testid="discovery-show-all"
            sx={{ display: 'block', mt: 0.75, ml: 1, py: 0.5, textAlign: 'left' }}
          >
            {showAll
              ? 'Show just the one we picked'
              : alsoRans === 1
                ? 'Show the other request'
                : `Show the other ${alsoRans} requests`}
          </Link>
        ) : null}
      </Collapse>
    </Box>
  );
}
