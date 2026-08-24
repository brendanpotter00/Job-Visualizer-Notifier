import type {
  DiscoveryOutcomeState,
  DiscoveryProgress,
  DiscoveryStep,
  DiscoveryStepKey,
  UserCompany,
} from '../../features/userCompanies/userCompaniesApi';

/** MUI `Chip` color slots we map health states onto. */
type ChipColor = 'default' | 'info' | 'success' | 'warning' | 'error';

export interface HealthBadge {
  label: string;
  color: ChipColor;
}

/**
 * Pure mapping from a company's `healthState` to a user-facing badge.
 *
 * Kept dependency-free so the whole matrix is testable without a store or a
 * render. `healthState` is a bare `str` on the wire (backend-owned), so an
 * unknown value must still produce a non-empty, non-alarming label rather than
 * a blank chip — the `default` branch echoes the raw code so a screenshot stays
 * diagnosable.
 *
 * FOUR user-visible states, one per colour, because four is what a person can
 * hold at a glance: setting up (blue), tracking (green), paused (amber), dead
 * (red). `discovering` is the provisional pre-tracking state (E7 capture pivot):
 * a non-ATS board whose one-time setup is still running — in progress, NOT an
 * error.
 *
 * `unverified` and `healthy` deliberately SHARE one green "Successfully
 * tracking" chip. The difference between them is whether the backend has an
 * oracle for that board yet, which is our problem and not something the user can
 * act on; splitting it produced a blue "Tracking — building history" chip that
 * read as "something is still wrong here" on a board that was working perfectly.
 * A working board says so, in green, in the same words in both states.
 *
 * ONE THING THIS CANNOT SAY: whether the board we read is the whole board. That is
 * not a `healthState` — a board tracked at partial scope is perfectly healthy — so it
 * lives beside this in `describeCompanyHealth`, which is what rows should call.
 */
export function describeHealthState(healthState: string): HealthBadge {
  switch (healthState) {
    case 'discovering':
      return { label: 'Setting up…', color: 'info' };
    // Tracked and working. Same words either side of the Phase-2 graduation.
    case 'unverified':
    case 'healthy':
      return { label: 'Successfully tracking', color: 'success' };
    case 'quarantined':
      // "Tracking paused", not "Paused", so the chip names WHAT stopped and stays
      // in the same vocabulary as the green one above it.
      return { label: 'Tracking paused', color: 'warning' };
    case 'refused':
      return { label: 'Not trackable', color: 'error' };
    default:
      // Unknown/newer code: surface it verbatim rather than blanking the chip.
      return { label: healthState || 'Unknown', color: 'default' };
  }
}

/**
 * The badge for a ROW, which is `describeHealthState` plus the one thing
 * `healthState` cannot say: we are only reading part of this board.
 *
 * A partial board is genuinely tracked — every job it can see is refreshed daily and
 * none is ever closed — so its `healthState` is `unverified`/`healthy` like any other
 * working company, and the green "Successfully tracking" chip was therefore accurate
 * about the plumbing and a lie about the board. Three measured boards sat behind it:
 * Binance tracked one department of fourteen, Kakao the tab its own page opened by
 * itself, Walmart ten jobs of forty-seven thousand.
 *
 * Amber rather than green, and it names WHAT is partial in the same vocabulary as
 * "Tracking paused" beside it. It is deliberately NOT red: nothing is broken and there
 * is nothing to fix — the checklist below the row carries the board's own numbers.
 *
 * The signal comes from the discovery blob, not from `healthState`, because the backend
 * decides it once at discovery from the captured bytes and there is no column for it —
 * see `OUTCOME_PARTIAL` in `api/services/discovery/progress.py`.
 */
export function describeCompanyHealth(
  company: Pick<UserCompany, 'healthState' | 'discovery'>,
): HealthBadge {
  if (
    (company.healthState === 'unverified' || company.healthState === 'healthy') &&
    company.discovery?.outcome === 'partial'
  ) {
    return { label: 'Tracking part of this board', color: 'warning' };
  }
  return describeHealthState(company.healthState);
}

/**
 * "Last checked" copy for a company row. Null (never harvested) is a normal
 * pre-first-run state, not an error — say so plainly.
 */
export function describeLastChecked(company: Pick<UserCompany, 'lastSuccessAt'>): string {
  if (!company.lastSuccessAt) {
    return 'Not yet checked';
  }
  const when = new Date(company.lastSuccessAt);
  if (Number.isNaN(when.getTime())) {
    return 'Not yet checked';
  }
  return `Last checked ${when.toLocaleString()}`;
}

// ── discovery checklist (E7 capture pivot) ─────────────────────────────────
//
// The one-time setup used to be a spinner because the retired DOM agent's work was
// genuinely unpredictable. The capture engine's steps are deterministic and known
// before the run starts, so they get NAMED — four rungs a person can watch tick
// across, in the order they happen.

/**
 * Label per step. `Record<DiscoveryStepKey, …>` on a CLOSED union, so a backend
 * rename is a compile error here rather than a blank rung in a list someone is
 * reading to decide what to do next.
 *
 * The KEYS are the backend's contract and never change here; the LABELS are ours
 * and describe what the user gets, not what the engine does. The engine "finds a
 * jobs feed" and "verifies a replay"; the person watching wants to know we read
 * their jobs and then built something that can keep reading them. Naming the rungs
 * after our internals is what made the previous set unreadable.
 */
export const DISCOVERY_STEP_LABELS: Record<DiscoveryStepKey, string> = {
  open_page: 'Opening the page',
  find_feed: 'Reading jobs',
  verify_read: 'Building web scraper',
  ready: 'Ready to track',
  first_scan: 'Reading the board',
};

/**
 * The step's label, unconditionally non-empty. `key` is typed as a closed union but
 * arrives as wire data, so an unrecognised value still renders something readable
 * rather than an empty row (same defensive stance as `describeHealthState`).
 */
export function describeDiscoveryStep(step: Pick<DiscoveryStep, 'key'>): string {
  return DISCOVERY_STEP_LABELS[step.key] ?? String(step.key);
}

/**
 * What the run finally did — read from `healthState` FIRST, not from the blob.
 *
 * The two can legitimately disagree: on a discovery timeout there is no terminal
 * checklist to write, so the row flips to `refused` while its blob still says
 * `running` from the last live update. That combination is the useful one (it shows
 * how far we got before the clock ran out) and it must read as a refusal, not as a
 * board still being worked on.
 */
export function resolveDiscoveryOutcome(
  company: Pick<UserCompany, 'healthState' | 'discovery'>,
): DiscoveryOutcomeState {
  if (company.healthState === 'refused') return 'refused';
  if (company.healthState === 'discovering') return 'running';
  return company.discovery?.outcome ?? 'running';
}

/**
 * Should this row show its checklist at all?
 *
 * `discovering` and `refused` are the whole point. A just-accepted board keeps its
 * "here's what we found" summary only until its first harvest lands — after that the
 * row is an ordinary tracked company and a permanent setup receipt is clutter. That
 * also means nothing has to sweep the blob away server-side.
 *
 * "The first harvest landed" is `lastSuccessAt`, NOT an empty job count. A board that
 * genuinely has zero open roles today (or one that closes all of them two months from
 * now) would otherwise resurrect a green "We can read {X}'s board" receipt above a
 * "0 open jobs" chip, linking to day-one postings the harvest has since proved gone.
 * `unverified` is required for the same reason: a `quarantined` row is one the backend
 * has marked broken, and a success receipt under a "Tracking paused" badge is the
 * UI contradicting the badge beside it.
 */
export function shouldShowDiscovery(
  company: Pick<UserCompany, 'healthState' | 'discovery' | 'lastSuccessAt'>,
): boolean {
  if (!company.discovery) return false;
  if (company.healthState === 'discovering' || company.healthState === 'refused') {
    return true;
  }
  // A PARTIAL board keeps its checklist forever, and that is the one place this panel
  // is not a setup receipt. The amber chip says we read part of the board; the checklist
  // is the only thing that says WHICH part and how we know ("read 8 jobs, but this
  // board's own category counts add up to 31"). Hiding it after the first harvest would
  // leave a permanent claim with its evidence deleted.
  if (resolveDiscoveryOutcome(company) === 'partial') {
    return company.healthState === 'unverified' || company.healthState === 'healthy';
  }
  return (
    company.healthState === 'unverified' &&
    resolveDiscoveryOutcome(company) === 'tracking' &&
    !company.lastSuccessAt
  );
}

/**
 * The one heading above the checklist, framed from the COMPANY's point of view.
 *
 * A bare string, and the ONLY prose the panel gets. This used to return a title, a
 * one-line "Opening the careers page ✓ · Finding the jobs feed ✕" chain AND a
 * severity — and the chain said, in one line, exactly what the four rungs below it
 * said in four. One fact, stated once: the heading names the verdict, the rungs
 * show how far we got, and the ✕ carries why.
 *
 * "Discovery failed" would tell the user nothing they can act on, so a refusal names
 * the company instead: this is about their board, not about our pipeline.
 */
export function describeDiscoveryOutcome(
  company: Pick<UserCompany, 'displayName' | 'healthState' | 'discovery'>,
): string {
  const outcome = resolveDiscoveryOutcome(company);
  if (outcome === 'refused') {
    return `We couldn't read ${company.displayName}'s board`;
  }
  if (outcome === 'partial') {
    // "Part of" rather than "some of": the shortfall is a SCOPE, not a sample. The
    // rungs below carry the board's own numbers, so the heading does not repeat them.
    return `We can only read part of ${company.displayName}'s board`;
  }
  if (outcome === 'tracking') {
    return `We can read ${company.displayName}'s board`;
  }
  return `Setting up ${company.displayName}`;
}

/**
 * The hosted live-view URL WHILE THERE IS STILL A BROWSER OPEN — otherwise null.
 *
 * The URL alone is not permission to render it. The backend publishes it the moment the
 * Browserbase session exists and then never clears it: the ledger keeps it for the
 * record, and the terminal write copies it back in. So a blob 200 seconds past the end
 * of the session still carries a URL that now points at nothing.
 *
 * `outcome === 'running'` is NOT the window either, and that was the bug. A run stays
 * `running` for its whole 240s budget, but the session is released in `capture_board`'s
 * `finally` — which returns straight into `ledger.finish(STEP_OPEN_PAGE)` +
 * `ledger.start(STEP_FIND_FEED)` + one publish. Capture is ~30s of a ~90s run, so the
 * frame spent the remaining minute pointed at a socket the backend had already closed,
 * and Browserbase's own inspector painted "WebSocket disconnected" across a 16:10 box
 * inside our page. Every successful run did this; it was never an error state.
 *
 * `open_page` being `active` IS the window, exactly, and for free: the same publish that
 * ticks that step over is the one that follows the release, so "step 1 is still running"
 * and "the browser is still open" are the same instant on the same write. No backend
 * signal needed — the one we want is already in the blob.
 *
 * The `outcome` check stays as the second half of the AND because a discovery TIMEOUT
 * freezes the last live snapshot with a step still `active` (see `renderedStatus`); a
 * run that is over has no browser open no matter what its stalled checklist says.
 */
export function watchableLiveViewUrl(
  company: Pick<UserCompany, 'healthState' | 'discovery'>,
): string | null {
  const url = company.discovery?.liveViewUrl;
  if (!url || resolveDiscoveryOutcome(company) !== 'running') {
    return null;
  }
  const openPage = company.discovery?.steps.find((step) => step.key === 'open_page');
  return openPage?.status === 'active' ? url : null;
}

/**
 * A byte count a person can read. Binary units, one decimal, no thousands separators
 * past KB — the number here is context for "is this the jobs feed or a tracking ping",
 * not an accounting figure.
 */
export function formatByteSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * The one line that stands in for the whole network log while it is collapsed.
 *
 * The log is closed by default (the panel it lives in was just cut back for being busy),
 * so this line is doing the work the log would otherwise do: it has to be specific
 * enough that a user knows whether opening it is worth it, and it has to MOVE while the
 * capture is running, because a count ticking up is what "we are watching your page
 * right now" looks like in one line.
 *
 * Null when there is nothing recorded — a page that fetched no JSON at all has no
 * evidence to offer, and the checklist's ✕ already says exactly that.
 */
export function describeNetworkSummary(
  company: Pick<UserCompany, 'healthState' | 'discovery'>,
): string | null {
  const network = company.discovery?.network;
  const requests = network?.requests ?? [];
  if (requests.length === 0) return null;
  // `recorded` over `requests.length`: the stored list is clipped to a size budget, and
  // the honest headline is what we SAW, not how much of it survived the budget.
  const count = Math.max(network?.recorded ?? 0, requests.length);
  const noun = count === 1 ? 'request' : 'requests';
  if (resolveDiscoveryOutcome(company) === 'running') {
    return `${count} ${noun} so far`;
  }
  if (requests.some((request) => request.state === 'chosen')) {
    return `${count} ${noun} · 1 picked`;
  }
  return `${count} ${noun} · none we could use`;
}

/** The step a refusal stopped on, or null (e.g. a timeout, which fails no step). */
export function failedDiscoveryStep(
  discovery: Pick<DiscoveryProgress, 'steps'> | null | undefined,
): DiscoveryStep | null {
  return discovery?.steps.find((step) => step.status === 'failed') ?? null;
}
