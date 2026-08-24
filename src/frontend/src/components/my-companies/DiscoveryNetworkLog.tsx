import { useState } from 'react';
import Box from '@mui/material/Box';
import ButtonBase from '@mui/material/ButtonBase';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type {
  DiscoveryPayloadSample,
  DiscoveryRequest,
  UserCompany,
} from '../../features/userCompanies/userCompaniesApi';
import { describeNetworkSummary, formatByteSize, resolveDiscoveryOutcome } from './companyHealth';

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
 * "Show me what you're actually doing" — the network log behind the checklist.
 *
 * COLLAPSED BY DEFAULT, in every state, and that is the whole design decision. The
 * panel above it was just cut from ~14 lines to ~8 because it was busy; a log of forty
 * requests unfurled under it would undo that on the first board that talks a lot. So the
 * default view stays exactly as calm as it is now and the evidence is one click away.
 *
 * What makes that honest rather than a place to hide things is the SUMMARY LINE, which
 * is never empty and never generic: it carries the live count while the browser is open
 * ("11 requests so far"), then the verdict ("14 requests · 1 picked", "14 requests ·
 * none we could use"). The count ticking up is the streaming, visible without opening
 * anything and costing one line — and if the user does want the detail, the line has
 * already told them how much of it there is.
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
  const [open, setOpen] = useState(false);
  const requests = company.discovery?.network?.requests ?? [];
  const summary = describeNetworkSummary(company);
  if (requests.length === 0 || summary === null) {
    return null;
  }
  const running = resolveDiscoveryOutcome(company) === 'running';
  const sample = company.discovery?.network?.sample ?? null;

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

      {/* `unmountOnExit` like the live-view section above it: a closed log is NOTHING,
          not forty hidden list items per row. The list is capped at 40 and this panel
          shows on every discovering/refused/partial row, so a user with ten refused
          boards would otherwise carry four hundred invisible nodes. Rows arriving while
          it is OPEN still animate individually, which is the case worth showing. */}
      <Collapse in={open} unmountOnExit>
        <Box
          component="ul"
          data-testid="discovery-request-list"
          sx={{ listStyle: 'none', m: 0, mt: 0.5, p: 0 }}
        >
          {requests.map((request, index) => (
            // Index keys on purpose: this list is append-only in arrival order, so the
            // index IS the row's identity. Keying on the URL would remount every row of
            // a board that fetches the same endpoint twice, replaying the arrival
            // animation on rows that did not just arrive.
            <RequestRow key={index} request={request} />
          ))}
        </Box>
        {sample ? <PayloadSample sample={sample} /> : null}
      </Collapse>
    </Box>
  );
}
