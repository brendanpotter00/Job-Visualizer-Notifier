import type {
  DiscoveryOutcomeState,
  DiscoveryProgress,
  DiscoveryRequest,
  DiscoveryStep,
  DiscoveryStepKey,
  UserCompany,
} from '../../features/userCompanies/userCompaniesApi';
import { TIME_UNITS } from '../../constants/time';

/** MUI `Chip` color slots we map health states onto. */
type ChipColor = 'default' | 'info' | 'success' | 'warning' | 'error';

export interface HealthBadge {
  label: string;
  color: ChipColor;
  /**
   * MUI `Chip` weight. Filled is the norm; OUTLINED is how a state says "this is a
   * fact about your board, not a thing to do about it".
   *
   * It exists because amber was doing that job and doing it wrong — see
   * `describeCompanyHealth`. Colour is reserved for severity (green working, amber
   * needs you, red dead); weight carries the qualifier inside a severity. That way a
   * complete board and a partial one differ at a glance — solid green vs hollow green
   * — without the partial one borrowing the colour that means "act on me".
   */
  variant?: 'filled' | 'outlined';
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
 * GREEN, OUTLINED — and it used to be amber, which was the bug. Amber is the colour
 * this app spends on "Tracking paused", i.e. something has gone wrong and you may need
 * to look at it. There is nothing to look at here: Microsoft's own feed is hard-capped
 * at 1,000 (100 pages × 10) and Amazon's at 10,000 of ~22,500, permanently, by their
 * API and not by anything we or the user can change. An alarm colour over a permanent
 * property of someone else's server trains people to ignore the colour — and it sat
 * directly above five green ticks, so the row read as a malfunction rather than as a
 * fact ("Why is this stuck in orange? All the steps are done").
 *
 * It is still not the same chip as a whole board, and that is the other half of the
 * fix: same hue, hollow instead of solid, and it names WHAT is partial. Solid green
 * "Successfully tracking" vs hollow green "Tracking part of this board" separates at a
 * glance without claiming anything is broken. The checklist below carries the board's
 * own numbers (`describePartialScope`), and the LAST RUNG carries the same fact — so
 * the chip now corroborates the list instead of contradicting it.
 *
 * The signal comes from the discovery blob, not from `healthState`, because the backend
 * decides it once at discovery from the captured bytes and there is no column for it —
 * see `OUTCOME_PARTIAL` in `api/services/discovery/progress.py`.
 */
export function describeCompanyHealth(
  company: Pick<UserCompany, 'healthState' | 'discovery' | 'lastSuccessAt'>
): HealthBadge {
  // BEFORE the partial check and before the green one, and that order is the whole
  // point — see `isFirstScanInFlight`. A row whose first harvest has not landed knows
  // nothing yet about how much of the board it got, so it must claim neither success
  // nor shortfall.
  if (company.healthState === 'unverified' && !company.lastSuccessAt) {
    return isFirstScanFailing(company)
      ? // The one thing we can say that stays true however long this lasts. Blue, not
        // amber: a harvest that failed tonight is retried tomorrow by the scheduler, and
        // there is nothing for the reader to do in between.
        { label: "Couldn't fetch yet — retrying", color: 'info' }
      : { label: 'Fetching all current jobs…', color: 'info' };
  }
  if (
    (company.healthState === 'unverified' || company.healthState === 'healthy') &&
    company.discovery?.outcome === 'partial'
  ) {
    return { label: 'Tracking part of this board', color: 'success', variant: 'outlined' };
  }
  return describeHealthState(company.healthState);
}

/**
 * Has the FIRST HARVEST reported yet? — the difference between "we are still fetching"
 * and "this is all there is", which the row used to render identically.
 *
 * THE MISREAD THIS EXISTS TO PREVENT, observed live: a row showing a settled chip, a
 * job count, and a fifth rung with a spinner on it. The reader took the chip as the
 * verdict on a fetch that was still running — reasonably, because nothing said
 * otherwise. Mid-fetch and settled were one pixel apart.
 *
 * A partial verdict is decided at DISCOVERY time, from the captured bytes, and the
 * harvest it enqueues runs afterwards — so `outcome: 'partial'` genuinely exists on a
 * row whose count is still climbing, and a chip reading "Tracking part of this board"
 * over a number that is not final is asserting the end of a story mid-sentence. Worse,
 * the count it sits above is the one the reader would use to check it.
 *
 * `first_scan` — the rung — is the signal here rather than `lastSuccessAt`, because this
 * one describes the PANEL, and the panel only exists on a discovered board where the
 * rung is authoritative. The row-level chip uses `lastSuccessAt` instead: an ATS company
 * (Workday, Greenhouse) has no checklist at all and still has a first-scan window, which
 * since `853457f` is ~20 seconds rather than ~15 minutes but is still a window in which
 * "Successfully tracking" over "0 open jobs" is a lie.
 *
 * `active` OR `failed`, both meaning "not landed yet": `failed` retries on the next
 * nightly harvest with nobody doing anything, so it is a fetch still in progress rather
 * than a finished one. `pending` is deliberately EXCLUDED — a blob written before this
 * rung existed has no entry for it and `read_progress` fills it in as `pending`, so
 * treating that as in-flight would strand every legacy row on "Fetching…" forever.
 */
export function isFirstScanInFlight(company: Pick<UserCompany, 'discovery'>): boolean {
  const scan = company.discovery?.steps.find((step) => step.key === 'first_scan');
  return scan?.status === 'active' || scan?.status === 'failed';
}

/**
 * Do we KNOW the first harvest has already tried and failed?
 *
 * The one guard against a chip that rots. `!lastSuccessAt` never expires on its own, so
 * "Fetching all current jobs…" would sit on a board that has been failing for three days
 * looking like it started a moment ago — an in-progress claim about a thing that is not
 * in progress. Where the checklist gives us the fact (a discovered board writes
 * `first_scan: failed` on every failed harvest), the chip says so instead.
 *
 * IT CANNOT COVER AN ATS ROW, which has no checklist: there is nothing on
 * `GET /api/users/companies` that distinguishes "added ten seconds ago" from "has failed
 * every night this week" — no created-at, no last-attempt, no last-failure. That is a
 * real gap and it needs a wire field, not a cleverer read of this one. Until then the
 * backstop is the backend's own: repeated failures quarantine the row, and the chip goes
 * amber — which is the right colour there, because a board that has stopped working IS
 * something the reader may want to act on.
 */
function isFirstScanFailing(company: Pick<UserCompany, 'discovery'>): boolean {
  return (
    company.discovery?.steps.some(
      (step) => step.key === 'first_scan' && step.status === 'failed'
    ) ?? false
  );
}

/**
 * Past this age a relative phrase stops helping. "47 days ago" is arithmetic the reader
 * has to undo, and a board nothing has fetched in a month is better named by its date.
 */
const RELATIVE_AGE_LIMIT_MS = 30 * TIME_UNITS.DAY;

/** The freshness line on a company row: what it says, and the exact instant behind it. */
export interface LastFetchLine {
  label: string;
  /**
   * The full timestamp for the row's `title`, or null when there is none. The relative
   * label rounds; this does not, so the precise value is one hover away rather than gone.
   */
  exactAt: string | null;
}

/**
 * The freshness line on a company row — WHEN WE LAST GOT JOBS, not when we last looked.
 *
 * THE LIE THIS REPLACES. The line read "Last checked <exact timestamp>" over
 * `lastSuccessAt`, and `lastSuccessAt` is stamped ONLY by a run that did not fail
 * (`mark_last_success`, called wherever `scrape_runs.success = true`). So a board the
 * scheduler hit every night and failed on every night said "Last checked 3 days ago" —
 * a claim that nobody had looked, about a board we had looked at three times. The board
 * read as merely quiet when it was actually broken. The number was right; the verb was
 * not.
 *
 * "Last fetched" is the same number under a verb that stays true in that case: a fetch
 * that failed fetched nothing, so the newest jobs we hold really are three days old. It
 * also moves the line from an event about us (we looked) to a fact about the count sitting
 * next to it (this is how old that number is), which is what the reader wanted anyway.
 *
 * NOT "Last full scrape", the first wording proposed. `lastSuccessAt` moves on any
 * non-FAILED run, VERIFIED *or* UNVERIFIED, and a knowingly-partial read is an ordinary
 * successful run — Microsoft's 2,055 of 2,075 stamps this field. "Full" would trade this
 * lie for a completeness claim we cannot back, on precisely the boards the hollow green
 * "Tracking part of this board" chip above it exists to be honest about.
 *
 * WHAT NO WORDING HERE CAN SAY: whether anything has tried since. The payload carries no
 * `lastAttemptAt`/`lastFailureAt` (the same gap `isFirstScanFailing` names), so on an ATS
 * row "added ten seconds ago" and "failing nightly for a week" are identical bytes. This
 * line is now honest about what it IS instead of implying it is that. "Last SUCCESSFUL
 * fetch" was rejected for the same reason: it advertises failures we cannot count, and
 * pointing at trouble the reader can neither see nor act on is the rule this area already
 * settled (see `describeCompanyHealth` on amber).
 *
 * RELATIVE, not the old `toLocaleString()`. The fact underneath is a nightly harvest, so
 * "8/24/2026, 10:10:22 PM" spent seconds-level precision on something good to the day and
 * made the reader do date arithmetic to answer their only question. Coarse buckets read
 * faster AND stop claiming a precision the fact does not have. The cost, named: a relative
 * string goes stale in a tab left open, because `receivedAt` advances only on a poll and a
 * settled list stops polling. Hour/day granularity hides nearly all of that drift, and
 * `exactAt` on the row's `title` is never wrong.
 *
 * `receivedAt` is the caller's `fulfilledTimeStamp`, NOT `Date.now()` — reading the clock
 * during render is lint-blocked as impure (see `isDiscoveryLive`). A zero/absent one means
 * we do not know the time, so the label falls back to the date rather than measuring an
 * age against the epoch and calling a three-day-old fetch "just now".
 */
export function describeLastFetched(
  company: Pick<UserCompany, 'lastSuccessAt'>,
  receivedAt: number
): LastFetchLine {
  // Never harvested is a normal pre-first-run state, not an error — say so plainly, and
  // in the same verb the in-flight chip uses ("Fetching all current jobs…").
  if (!company.lastSuccessAt) {
    return { label: 'Not fetched yet', exactAt: null };
  }
  const when = new Date(company.lastSuccessAt);
  if (Number.isNaN(when.getTime())) {
    return { label: 'Not fetched yet', exactAt: null };
  }

  const exactAt = when.toLocaleString();
  const ageMs = receivedAt - when.getTime();
  if (!Number.isFinite(receivedAt) || receivedAt <= 0 || ageMs >= RELATIVE_AGE_LIMIT_MS) {
    return { label: `Last fetched ${when.toLocaleDateString()}`, exactAt };
  }
  return { label: `Last fetched ${describeAge(ageMs)}`, exactAt };
}

/**
 * Age → the phrase a person would say. Coarse on purpose: the underlying event is a
 * nightly harvest, so a finer grain would be inventing confidence.
 *
 * A NEGATIVE age falls in the first branch and reads "just now" — that is clock skew
 * between the server that stamped the row and this browser, not a fetch from the future,
 * and it is the same call `isDiscoveryLive` makes about a forward-dated `updatedAt`.
 */
function describeAge(ageMs: number): string {
  if (ageMs < TIME_UNITS.MINUTE) {
    return 'just now';
  }
  if (ageMs < TIME_UNITS.HOUR) {
    return countAgo(ageMs / TIME_UNITS.MINUTE, 'minute');
  }
  if (ageMs < TIME_UNITS.DAY) {
    return countAgo(ageMs / TIME_UNITS.HOUR, 'hour');
  }
  return countAgo(ageMs / TIME_UNITS.DAY, 'day');
}

/**
 * `1.9 → "1 hour ago"` — floors, the "one and a bit" reading every elapsed-time UI uses,
 * so the error is bounded by one unit and always in the direction a reader expects. It is
 * the reason `exactAt` exists: the rounded phrase is for scanning, the tooltip is exact.
 */
function countAgo(value: number, unit: string): string {
  const count = Math.floor(value);
  return `${count} ${unit}${count === 1 ? '' : 's'} ago`;
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
  // "Fetching all current jobs", not "Reading the board": this rung is the FIRST
  // HARVEST, and what it does is pull down every posting the board will hand us. It is
  // also the rung that a partial board cannot honestly tick — which is the point. The
  // word "all" is what makes `renderedStatus`'s ◐ mean something; a vaguer label would
  // have let a 1,000-of-22,500 board keep a plain ✓ and keep contradicting its chip.
  first_scan: 'Fetching all current jobs',
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
  company: Pick<UserCompany, 'healthState' | 'discovery'>
): DiscoveryOutcomeState {
  if (company.healthState === 'refused') return 'refused';
  if (company.healthState === 'discovering') return 'running';
  return company.discovery?.outcome ?? 'running';
}

/**
 * Should this row show its checklist at all?
 *
 * NOW: whenever there is one to show, except on a `quarantined` row. It used to
 * disappear the moment `lastSuccessAt` was set, on the reasoning that a permanent setup
 * receipt is clutter — and that reasoning was right about a panel that was always
 * expanded. It is no longer one: the checklist is a COLLAPSED accordion once a row has
 * settled (`shouldExpandDiscovery`), so what a tracked row now carries forever is one
 * caption-sized line. Clutter was the entire cost, and the accordion pays it.
 *
 * What the old rule cost, measured on the owner's own list: he assumed the evidence was
 * gone ("I'm assuming if I refresh it all goes away"). It never was — the blob is 5 KB
 * of `provider_config->'discovery'` and survives every reload — but a panel that
 * vanishes on the first harvest is indistinguishable from one that was deleted. The one
 * record of HOW we read a board (which request we picked out of sixteen, the JSON it
 * returned) is worth more than the line it costs, and now it costs a line.
 *
 * `quarantined` is still excluded, and for the original reason: that row is one the
 * backend has marked broken, and a "We can read {X}'s board" receipt under a "Tracking
 * paused" badge is the UI contradicting the badge beside it. Any UNKNOWN/newer
 * `healthState` is excluded too — same defensive stance as `describeHealthState`, since
 * we cannot know whether a state we have never heard of makes the receipt a lie.
 */
export function shouldShowDiscovery(
  company: Pick<UserCompany, 'healthState' | 'discovery' | 'lastSuccessAt'>
): boolean {
  if (!company.discovery) return false;
  return (
    company.healthState === 'discovering' ||
    company.healthState === 'refused' ||
    company.healthState === 'unverified' ||
    company.healthState === 'healthy'
  );
}

/**
 * Should the checklist start OPEN, or as one collapsed line?
 *
 * ONE rule: open while something is still happening, or while something went wrong.
 * Closed once the row has settled into an ordinary tracked company.
 *
 * `lastSuccessAt` is what "settled" means, and it is the same signal the old
 * `shouldShowDiscovery` used to DELETE the panel on — the change is that the evidence
 * now folds away instead of being thrown away. So:
 *  - `discovering` → open. The rungs ticking and the requests arriving ARE the feature;
 *    a one-time setup that happens inside a closed box is the spinner it replaced.
 *  - `refused` → open. The verdict and the one action that changes it must not need a
 *    click to find, and it stays open even though a refused row can never harvest.
 *  - accepted, first harvest not yet landed → open. `first_scan` is still spinning.
 *  - tracked and harvested (including a PARTIAL board) → closed. This is the scannable
 *    state: a list of rows, each one line of evidence away from its receipt.
 *
 * Read ONCE, as a `useState` initial value, deliberately: a harvest landing mid-read
 * must not snap the panel shut under someone who is looking at it.
 */
export function shouldExpandDiscovery(
  company: Pick<UserCompany, 'healthState' | 'discovery' | 'lastSuccessAt'>
): boolean {
  return resolveDiscoveryOutcome(company) === 'refused' || !company.lastSuccessAt;
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
  company: Pick<UserCompany, 'displayName' | 'healthState' | 'discovery'>
): string {
  const outcome = resolveDiscoveryOutcome(company);
  if (outcome === 'refused') {
    return `We couldn't read ${company.displayName}'s board`;
  }
  // AHEAD of the verdicts below, matching the chip (`describeCompanyHealth`): while the
  // first harvest is still running we do not yet know how much of the board we got, so
  // the heading narrates instead of concluding. Same words as the rung and the chip —
  // one action keeps one name the whole way down the row.
  if (outcome !== 'running' && isFirstScanInFlight(company)) {
    return `Fetching ${company.displayName}'s jobs`;
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
 * The board's own numbers behind a `partial` verdict — the sentence that goes UNDER the
 * last rung — or null when we cannot state them.
 *
 * THE INCONSISTENCY THIS CLOSES. A partial row used to render five unqualified ✓s,
 * ending in one that read as complete success, under a chip saying we only read part of
 * the board. Two things disagreeing, and the chip lost: it looked like a malfunction.
 * The chip was the correct one, so the fix is to make the last rung say what it actually
 * achieved. Then the chip corroborates the list.
 *
 * The numbers exist in exactly ONE place on the wire, and it is prose: `verify_read`'s
 * result, which the backend composes as
 *
 *     read {N} job(s), but {board's own claim} — we can only track part of this board
 *
 * (see `_coverage` / `STEP_VERIFY_READ` in `api/services/capture/discover.py`). We take
 * the middle clause and nothing else, on purpose:
 *
 *  - the LEADING "read {N} job(s)" is the ACCEPTANCE PROBE's count, clamped to two pages
 *    — 20 for Microsoft, on a row whose chip beside it says "1,000 open jobs". Rendering
 *    it would answer one confusion with a worse one, so the left-hand number comes from
 *    `openJobCount` instead: what we actually hold, live, and already on the row.
 *  - the TRAILING verdict is what `describeDiscoveryOutcome` says one line above. Said
 *    twice it is noise; the heading names the scope, the rung names the numbers.
 *
 * Split on the separators rather than on the numbers, because the claim itself is one of
 * three templates with a formatted count in it ("this board's own facets agree on
 * 22,500 job(s)", "…category counts add up to 47,000") and pattern-matching those would
 * break the moment a fourth is added. Anything that does not parse returns null and the
 * rung simply carries its ◐ with no caption — a missing sentence, never a wrong one.
 *
 * A SNAPSHOT, not a live figure: the claim is what the board published about itself on
 * the day we captured it, and the rung is a setup rung, so a board that has since grown
 * is described by the count we measured. That is the honest thing for a receipt to say
 * and the reason it lives on a rung rather than in the chip.
 */
export function describePartialScope(
  company: Pick<UserCompany, 'discovery' | 'openJobCount'>
): string | null {
  const verified = company.discovery?.steps.find((step) => step.key === 'verify_read');
  const [, afterBut] = (verified?.result ?? '').split(', but ');
  const claim = afterBut?.split(' — ')[0]?.trim();
  if (!claim) return null;
  const sentence = claim.charAt(0).toUpperCase() + claim.slice(1);
  if (company.openJobCount <= 0) {
    return `${sentence}.`;
  }
  return `${sentence}; we can reach ${company.openJobCount.toLocaleString()}.`;
}

/**
 * Faster list cadence while a one-time discovery is actually running.
 *
 * Its four steps take seconds each, so the ordinary 15s poll would show a checklist that
 * jumps two rungs at a time and is usually already stale — the same opaque wait the
 * checklist exists to remove. `MyCompaniesList` owns the cadence; it lives HERE because
 * `DiscoveryChecklist` derives its live-view trust window from the same number
 * (`LIVE_VIEW_TRUST_MS`), and those two must never drift apart: "how long may we go
 * without hearing from the server before we stop believing it" is only answerable if you
 * know how often we ask. A local copy in each file would let a cadence change quietly
 * turn the trust window into either a flicker or a no-op.
 */
export const DISCOVERY_POLL_INTERVAL_MS = 4_000;

/**
 * The hosted live-view URL WHILE THERE IS STILL A BROWSER OPEN — otherwise null.
 *
 * The URL used to outlive its own session: the backend published it the moment the
 * Browserbase session existed and then never cleared it, so a blob 200 seconds past the
 * end of the session still carried a URL pointing at a closed socket. Browserbase's own
 * inspector painted "Debugging connection was closed. Reason: WebSocket disconnected"
 * across a 16:10 box inside our page — on every SUCCESSFUL run, never an error state.
 *
 * The backend now CLEARS `live_view_url` in the same write that releases the session, so
 * the server states the fact and this function mostly consumes it.
 *
 * IT IS NOT `open_page` BEING `active`, and that was the previous fix's mistake. The
 * theory was that the release in `capture_board`'s `finally` returns straight into
 * `ledger.finish(STEP_OPEN_PAGE)`, making "step 1 is still running" the same instant as
 * "the browser is still open". A screenshot disproved it: `Opening the page` was still
 * bold with its spinner turning while the frame beneath it already read "WebSocket
 * disconnected". The CDP socket dies when the BROWSER closes, which is strictly earlier
 * than the ledger write that ticks the step over, and that gap is exactly where the dead
 * frame lives. Never infer browser liveness from step state — it is always at least one
 * write behind the thing it is guessing at.
 *
 * `outcome === 'running'` stays as the second half of the AND, belt-and-braces: a
 * discovery TIMEOUT freezes the last live snapshot instead of writing a terminal one
 * (see `renderedStatus`), so a stalled blob can still carry a URL the killed task never
 * reached the code to clear. A run that is over has no browser open, whatever it says.
 *
 * WHAT THIS FUNCTION CANNOT DO, and the reason `DiscoveryChecklist` does not stop here:
 * it reports what the LAST PAYLOAD said, and the payload is always behind the socket.
 * The browser dies inside the capture child (`_capture_main.py`'s `await browser.close()`
 * is its last act); the parent only regains control once that child has exited, and only
 * then writes the null. The DevTools frame has already painted "Debugging connection was
 * closed" by the time the write happens, let alone by the time a poll carries it here —
 * so this null is never early, it is at best one poll late, and if polls are FAILING
 * (RTK Query keeps serving the last good payload, warning banner and all) or the row has
 * aged out of the fast cadence, it is late without bound. Closing that is a client-side
 * job and it lives in `DiscoveryChecklist`'s `LiveView`; see `LIVE_VIEW_TRUST_MS`.
 */
export function watchableLiveViewUrl(
  company: Pick<UserCompany, 'healthState' | 'discovery'>
): string | null {
  const url = company.discovery?.liveViewUrl;
  if (!url || resolveDiscoveryOutcome(company) !== 'running') {
    return null;
  }
  return url;
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
 * The request we picked, or null while we are still looking (and forever, on a refusal).
 *
 * ONE predicate, exported, because two things narrow on it and they must never disagree:
 * the log shows this row alone once it exists, and `describeNetworkSummary` above it
 * says "· 1 picked". A local `.find()` in each would eventually drift into a heading
 * that counts a winner the list is not showing.
 *
 * Deliberately NOT keyed on the run being over. `choose_request` is written during
 * `verify_read` — after the acceptance replay proves the recipe, but before the terminal
 * write flips `health_state` — so there is a real window where a winner exists on a run
 * that is still `running`. The panel should narrow the moment we know, not a poll later.
 */
export function chosenDiscoveryRequest(
  company: Pick<UserCompany, 'discovery'>
): DiscoveryRequest | null {
  return company.discovery?.network?.requests.find((r) => r.state === 'chosen') ?? null;
}

/**
 * The one line that heads the network log — and, once a request is picked, the only
 * place the discarded ones are still counted.
 *
 * The log is OPEN by default now, so this is no longer a stand-in for rows nobody can
 * see; it is the frame around them. Two jobs, both load-bearing:
 *
 * - while the capture runs it has to MOVE, because a count ticking up is what "we are
 *   watching your page right now" looks like in one line; and
 * - once we have picked one, the list below narrows to that single row — so `14
 *   requests · 1 picked` is the only thing left saying there were fourteen. Dropping the
 *   total here would turn "we chose this out of fourteen" into "we saw one thing".
 *
 * `recorded` over `requests.length` for the same reason: the stored list is clipped to a
 * size budget, and the honest headline is what we SAW.
 *
 * Null when there is nothing recorded — a page that fetched no JSON at all has no
 * evidence to offer, and the checklist's ✕ already says exactly that.
 */
export function describeNetworkSummary(
  company: Pick<UserCompany, 'healthState' | 'discovery'>
): string | null {
  const network = company.discovery?.network;
  const requests = network?.requests ?? [];
  if (requests.length === 0) return null;
  // `recorded` over `requests.length`: the stored list is clipped to a size budget, and
  // the honest headline is what we SAW, not how much of it survived the budget.
  const count = Math.max(network?.recorded ?? 0, requests.length);
  const noun = count === 1 ? 'request' : 'requests';
  // "Did we pick one" is asked BEFORE "is it still running", so this line always
  // describes the list directly beneath it. The other order let a winner written during
  // `verify_read` narrow the list to one row under a heading still saying "so far".
  if (chosenDiscoveryRequest(company) !== null) {
    return `${count} ${noun} · 1 picked`;
  }
  if (resolveDiscoveryOutcome(company) === 'running') {
    return `${count} ${noun} so far`;
  }
  return `${count} ${noun} · none we could use`;
}

/** The step a refusal stopped on, or null (e.g. a timeout, which fails no step). */
export function failedDiscoveryStep(
  discovery: Pick<DiscoveryProgress, 'steps'> | null | undefined
): DiscoveryStep | null {
  return discovery?.steps.find((step) => step.status === 'failed') ?? null;
}

/**
 * Where each ATS publishes the human-readable board for a bare slug — the LEGACY
 * derivation, kept only for a payload that predates `boardUrl`.
 *
 * These four are the ones whose `board_token` IS the slug the public board is addressed
 * by (`ats_link_resolver.py` extracts exactly that), so the URL is a template and nothing
 * else is needed. Greenhouse gets `job-boards.` rather than the older `boards.` host: the
 * backend accepts both as input and the old one 301s to this one, so emitting the
 * destination saves every reader a redirect.
 *
 * WORKDAY AND EIGHTFOLD ARE STILL DELIBERATELY ABSENT, and that is why this is a lookup
 * rather than a switch with a default. Their `board_token` is a cosmetic tenant label —
 * `blueorigin`, `netflix` — and the real board lives at a host the token does not spell
 * (`https://<tenant>.wd5.myworkdayjobs.com/<career_site>`,
 * `https://explore.jobs.netflix.net/careers?domain=…`). Both parts live in
 * `provider_config`, which is not on the wire, so guessing here would produce a confident
 * link to a 404. The server now sends the real thing (`boardUrl`); this table must never
 * grow those two, because the only version of them it could ever hold is a guess.
 */
const ATS_BOARD_HOSTS: Record<string, string> = {
  greenhouse: 'https://job-boards.greenhouse.io',
  ashby: 'https://jobs.ashbyhq.com',
  lever: 'https://jobs.lever.co',
  gem: 'https://jobs.gem.com',
};

/** `ats` for a board we discovered ourselves, whose `boardToken` is the pasted URL. */
const DISCOVERED_ATS = 'discovered';

/**
 * The board this company was built from — a real, openable URL, or null.
 *
 * THE QUESTION IT ANSWERS: "what did we actually read to make this?" A tracked row showed
 * a name, a chip, a count and a freshness line, and nothing anywhere said which page it
 * came from — so when a board started serving dead job links there was no way to go and
 * look at it without opening the database. It got sharper once a company could be added
 * by NAME: you type "Cisco", we search, we pick a board, and the row you get back has to
 * be able to tell you WHICH board, or you cannot check that we found the right company.
 *
 * THE ANSWER IS THE SERVER'S. `boardUrl` is computed in `api/services/board_url.py`, from
 * `provider_config` — the only place Workday's real host (`base_url` + `career_site_slug`)
 * and Eightfold's (`tenant_host` + `domain`) exist. Those two are precisely the providers
 * this file could never build a link for, and the Cisco case is a Workday board, so the
 * headline example rendered nothing. Teaching the browser those shapes would mean putting
 * `provider_config` on the wire and keeping a second copy of every provider's URL grammar
 * in sync with the backend's; asking the server for one string does neither.
 *
 * THE LOCAL DERIVATION SURVIVES AS A FALLBACK, for one reason: the frontend and the
 * backend deploy separately, so a Vercel deploy can land ahead of the Railway one and
 * serve a payload with no `boardUrl` KEY AT ALL. Without the fallback, every Greenhouse /
 * Ashby / Lever / Gem link that works today would vanish for that window. It covers what
 * it always covered and still refuses to guess Workday or Eightfold.
 *
 * ABSENT AND NULL ARE THEREFORE DIFFERENT THINGS, and collapsing them would undo half of
 * this. Absent is "we are talking to a server that predates the field" → derive what we
 * safely can. `null` is that server's considered answer — it looked at the config and
 * could not name an honest destination — and it WINS, because falling back there would
 * be this file overruling the only code that can see the row.
 *
 * NULL IS A REAL ANSWER and callers must render nothing for it, never a dead link. It
 * comes back for that case, and for anything that does not parse as `http(s)`: these
 * values are server data, but they ORIGINATE in something a stranger pasted, and an
 * `href` is the one place that distinction matters. The scheme check is what keeps a
 * `javascript:` URL from becoming a link — applied to the server's answer too, because
 * the check costs nothing and "the server sent it" is not the property that makes a
 * string safe to put in an `href`.
 */
export function sourceBoardUrl(
  company: Pick<UserCompany, 'ats' | 'boardToken' | 'boardUrl'>
): string | null {
  if (company.boardUrl !== undefined) {
    const served = company.boardUrl?.trim();
    return served && isHttpUrl(served) ? served : null;
  }
  const token = company.boardToken?.trim();
  if (!token) return null;
  if (company.ats === DISCOVERED_ATS) {
    return isHttpUrl(token) ? token : null;
  }
  const host = ATS_BOARD_HOSTS[company.ats];
  return host ? `${host}/${encodeURIComponent(token)}` : null;
}

/** `http(s)` and nothing else — the one gate between stored text and an `href`. */
function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

/**
 * What that link SAYS — the board's host, `www.` stripped.
 *
 * The host rather than a fixed word like "Board", because the host is the part that
 * answers the question without a click: `janestreet.com` under a row named "Jane Street"
 * is a confirmation, and `job-boards.greenhouse.io` tells an ATS row's reader the thing
 * they actually want to know. A uniform label would make every row's link identical and
 * push the answer behind a navigation.
 *
 * The full URL belongs in a `title` — the same division the freshness line already makes:
 * the short form is for scanning the list, the exact value is for the one row you care
 * about. Null if it will not parse, so a label can never disagree with its own href.
 */
export function sourceBoardLabel(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./i, '') || null;
  } catch {
    return null;
  }
}
