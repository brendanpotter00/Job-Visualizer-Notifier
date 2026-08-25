import { useState } from 'react';
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
 * The payload sample, in its own scroll box.
 *
 * `pre-wrap` + `break-word` rather than `pre` + horizontal scroll: a nested scroll
 * region that only scrolls sideways is close to undiscoverable on a phone, and this
 * panel lives inside a list row. The page itself must never scroll sideways, which is
 * the constraint that decides this — nothing here can be wider than its container.
 */
function PayloadSample({ sample }: { sample: DiscoveryPayloadSample }) {
  return (
    <Box sx={{ mt: 1 }} data-testid="discovery-payload-sample">
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
          p: 1,
          maxHeight: 220,
          overflow: 'auto',
          overscrollBehavior: 'contain',
          bgcolor: 'background.paper',
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          fontFamily: MONO,
          fontSize: '0.7rem',
          lineHeight: 1.55,
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
function RequestRow({ request }: { request: DiscoveryRequest }) {
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
  const [open, setOpen] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const requests = company.discovery?.network?.requests ?? [];
  const summary = describeNetworkSummary(company);
  if (requests.length === 0 || summary === null) {
    return null;
  }
  const running = resolveDiscoveryOutcome(company) === 'running';
  const sample = company.discovery?.network?.sample ?? null;
  // Keyed on the winner EXISTING, not on the run being over: `choose_request` is written
  // during `verify_read`, one publish before the terminal write, so narrowing on the
  // outcome would leave a settled answer looking like an open search for a poll longer.
  const narrowed = chosenDiscoveryRequest(company) !== null && !showAll;
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
          {requests.map((request, index) =>
            // The FULL list is mapped and the also-rans are dropped here rather than
            // filtered upstream, so `index` stays the row's position in the capture. That
            // is what keeps the picked row's DOM node identical across "show all" — key
            // it by position-within-the-visible-list instead and the one row the user is
            // reading remounts and replays its arrival animation on every toggle.
            //
            // Index keys at all because this list is append-only in arrival order, so the
            // index IS the row's identity. Keying on the URL would remount every row of a
            // board that fetches the same endpoint twice.
            narrowed && request.state !== 'chosen' ? null : (
              <RequestRow key={index} request={request} />
            ),
          )}
        </Box>
        {/* The payload belongs to the picked row, so it sits directly under the list —
            which in the narrowed state means directly under the one row it came from. */}
        {sample ? <PayloadSample sample={sample} /> : null}
        {/* LAST, and caption-sized. The winner and its JSON are the answer; this is the
            footnote for the one person who wants to argue with it. Rendered only when
            there is genuinely something behind it — a board whose only recorded request
            IS the winner has no "others" to show. */}
        {alsoRans > 0 && chosenDiscoveryRequest(company) !== null ? (
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
