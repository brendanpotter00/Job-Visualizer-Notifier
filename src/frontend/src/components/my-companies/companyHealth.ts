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
  if (outcome === 'tracking') {
    return `We can read ${company.displayName}'s board`;
  }
  return `Setting up ${company.displayName}`;
}

/** The step a refusal stopped on, or null (e.g. a timeout, which fails no step). */
export function failedDiscoveryStep(
  discovery: Pick<DiscoveryProgress, 'steps'> | null | undefined,
): DiscoveryStep | null {
  return discovery?.steps.find((step) => step.status === 'failed') ?? null;
}
