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
 * `discovering` is the provisional pre-tracking state (E7 capture pivot): a
 * non-ATS board whose one-time browser-agent setup is still running — it isn't
 * tracked yet, so it reads as "Setting up…" (neutral, in progress), NOT as an
 * error. `unverified` (no oracle yet) then reads as steady progress —
 * "building history". Phase 2 graduates a proven company to `healthy`, whose
 * badge stays in the same "Tracking — …" family so the states read as one
 * continuum rather than unrelated words.
 */
export function describeHealthState(healthState: string): HealthBadge {
  switch (healthState) {
    case 'discovering':
      return { label: 'Setting up…', color: 'info' };
    case 'unverified':
      return { label: 'Tracking — building history', color: 'info' };
    case 'healthy':
      return { label: 'Tracking — healthy', color: 'success' };
    case 'quarantined':
      return { label: 'Paused — needs a look', color: 'warning' };
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
// before the run starts, so they get NAMED — and each finished one carries the
// specific thing it found, which is what lets a user tell whether the board we're
// about to track is theirs.

/**
 * Label per step. `Record<DiscoveryStepKey, …>` on a CLOSED union, so a backend
 * rename is a compile error here rather than a blank rung in a list someone is
 * reading to decide what to do next.
 */
export const DISCOVERY_STEP_LABELS: Record<DiscoveryStepKey, string> = {
  open_page: 'Opening the careers page',
  find_feed: 'Finding the jobs feed',
  verify_read: 'Verifying we can read it',
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
 */
export function shouldShowDiscovery(
  company: Pick<UserCompany, 'healthState' | 'discovery' | 'openJobCount'>,
): boolean {
  if (!company.discovery) return false;
  if (company.healthState === 'discovering' || company.healthState === 'refused') {
    return true;
  }
  return resolveDiscoveryOutcome(company) === 'tracking' && company.openJobCount === 0;
}

export interface DiscoveryHeadline {
  title: string;
  /** The one-line ✓/✕ chain across the steps, or '' while nothing has landed yet. */
  summary: string;
  severity: 'info' | 'success' | 'error';
}

/**
 * The heading above the checklist, framed from the COMPANY's point of view.
 *
 * A refusal says "we couldn't read {name}'s board" and then names the step — "Found
 * the feed ✓ · Couldn't confirm the results match ✕". "Discovery failed" tells the
 * user nothing they can act on; which step stopped tells them whether to paste a
 * different URL or to give up on this site.
 */
export function describeDiscoveryOutcome(
  company: Pick<UserCompany, 'displayName' | 'healthState' | 'discovery' | 'openJobCount'>,
): DiscoveryHeadline {
  const outcome = resolveDiscoveryOutcome(company);
  const steps = company.discovery?.steps ?? [];
  const summary = steps
    .filter((step) => step.status === 'done' || step.status === 'failed')
    .map((step) => `${describeDiscoveryStep(step)} ${step.status === 'done' ? '✓' : '✕'}`)
    .join(' · ');

  if (outcome === 'refused') {
    return {
      title: `We couldn't read ${company.displayName}'s board`,
      summary,
      severity: 'error',
    };
  }
  if (outcome === 'tracking') {
    return {
      title: `We can read ${company.displayName}'s board`,
      summary,
      severity: 'success',
    };
  }
  return {
    title: `Setting up ${company.displayName}`,
    summary,
    severity: 'info',
  };
}

/** The step a refusal stopped on, or null (e.g. a timeout, which fails no step). */
export function failedDiscoveryStep(
  discovery: Pick<DiscoveryProgress, 'steps'> | null | undefined,
): DiscoveryStep | null {
  return discovery?.steps.find((step) => step.status === 'failed') ?? null;
}
