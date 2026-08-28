import type {
  AttemptOutcome,
  CustomCompanyLiveStatus,
} from '../../features/admin/adminApi';
import type { FacetOption } from '../../types';

/**
 * Pure mapping from the three wire vocabularies on this page — live status,
 * attempt outcome, board health — to the single chip each renders as.
 * React-free (mirrors `AdminEnrichmentPage/outcomeChip.ts`) so the whole matrix
 * is testable without a render.
 *
 * TWO axes, and the second one is the part that is easy to get backwards:
 *
 *  - COLOUR carries severity (green fine, blue informational, amber needs a
 *    look, red broken).
 *  - WEIGHT carries whether it is a problem at all. `outlined` = good or
 *    neutral; `filled` = bad. A solid chip is the page shouting; a hollow one
 *    is it stating a fact. That inversion is this repo's severity signal
 *    (`components/my-companies/companyHealth.ts` uses the same one), and it is
 *    what lets a screenful of chips be scanned without reading a single label.
 *
 * Every map is typed as a total `Record<…>` over its closed union, so a value
 * the backend adds later is a compile error here rather than a blank chip.
 */

export type ChipColor = 'default' | 'info' | 'success' | 'warning' | 'error';

export interface StatusChip {
  label: string;
  color: ChipColor;
  variant: 'filled' | 'outlined';
}

const LIVE_STATUS_CHIPS: Record<CustomCompanyLiveStatus, StatusChip> = {
  live: { label: 'Live', color: 'success', variant: 'outlined' },
  stale: { label: 'Stale', color: 'warning', variant: 'filled' },
  failing: { label: 'Failing', color: 'error', variant: 'filled' },
  never_harvested: { label: 'Never harvested', color: 'warning', variant: 'filled' },
  // An orphan is a data-integrity problem (a board nobody owns), not a
  // scraping one — amber rather than red, but still filled: something is wrong.
  orphan: { label: 'Orphan', color: 'warning', variant: 'filled' },
};

export function liveStatusChip(status: CustomCompanyLiveStatus): StatusChip {
  // `?? ` guards the wire, not the type: `liveStatus` is a bare string on the
  // backend, so an unrecognised value must still render something diagnosable
  // rather than an empty chip.
  return LIVE_STATUS_CHIPS[status] ?? { label: String(status), color: 'default', variant: 'outlined' };
}

const ATTEMPT_OUTCOME_CHIPS: Record<AttemptOutcome, StatusChip> = {
  added: { label: 'added', color: 'success', variant: 'outlined' },
  already_public: { label: 'already public', color: 'info', variant: 'outlined' },
  // In flight and legitimately so — neutral, not an alarm.
  pending: { label: 'pending', color: 'default', variant: 'outlined' },
  // Past the sweeper's grace: the reconciler should have refused this and did
  // not. Amber-filled, because it is our bug rather than the board's.
  stuck: { label: 'stuck', color: 'warning', variant: 'filled' },
  refused: { label: 'refused', color: 'error', variant: 'filled' },
  unsupported: { label: 'unsupported', color: 'error', variant: 'filled' },
  empty: { label: 'empty', color: 'warning', variant: 'filled' },
  probe_failed: { label: 'probe failed', color: 'error', variant: 'filled' },
};

export function attemptOutcomeChip(outcome: AttemptOutcome): StatusChip {
  return (
    ATTEMPT_OUTCOME_CHIPS[outcome] ?? { label: String(outcome), color: 'default', variant: 'outlined' }
  );
}

/**
 * `companies.health_state` is a bare `str` on the wire (backend-owned), so this
 * one is keyed loosely on purpose and the default branch ECHOES the raw code
 * rather than blanking the cell — a screenshot of an unknown state should still
 * be diagnosable.
 */
const HEALTH_STATE_CHIPS: Record<string, StatusChip> = {
  healthy: { label: 'healthy', color: 'success', variant: 'outlined' },
  unverified: { label: 'unverified', color: 'warning', variant: 'filled' },
  discovering: { label: 'discovering', color: 'info', variant: 'outlined' },
  quarantined: { label: 'quarantined', color: 'error', variant: 'filled' },
  refused: { label: 'refused', color: 'error', variant: 'filled' },
};

export function healthStateChip(health: string | null): StatusChip {
  if (health === null) {
    return { label: '—', color: 'default', variant: 'outlined' };
  }
  return HEALTH_STATE_CHIPS[health] ?? { label: health, color: 'default', variant: 'outlined' };
}

/**
 * Options for the Health dropdown over Table 1. Static rather than derived from
 * `summary.byHealthState`, so a state with zero rows today is still selectable
 * (filtering to it and getting an empty table is a legitimate answer).
 */
export const HEALTH_STATE_OPTIONS: FacetOption[] = [
  { slug: 'discovering', label: 'discovering', sortOrder: 0 },
  { slug: 'unverified', label: 'unverified', sortOrder: 1 },
  { slug: 'healthy', label: 'healthy', sortOrder: 2 },
  { slug: 'quarantined', label: 'quarantined', sortOrder: 3 },
  { slug: 'refused', label: 'refused', sortOrder: 4 },
];

/**
 * Options for the Outcome dropdown over Table 2, in "how did it end" order:
 * the successes, then in-flight, then the failures. Labels reuse the chip
 * labels so the dropdown and the cell say the same word.
 */
export const ATTEMPT_OUTCOME_OPTIONS: FacetOption[] = (
  [
    'added',
    'already_public',
    'pending',
    'stuck',
    'refused',
    'unsupported',
    'empty',
    'probe_failed',
  ] as const
).map((slug, index) => ({
  slug,
  label: ATTEMPT_OUTCOME_CHIPS[slug].label,
  sortOrder: index,
}));
