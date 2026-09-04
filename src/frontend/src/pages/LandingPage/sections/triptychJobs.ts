/**
 * Selection logic for the three-slot fresh-jobs triptych, pure for testability.
 *
 * Three themed slots stand side by side, each flipping through its own small
 * pool. The one rule that makes the row read as three different answers instead
 * of one answer printed three times: **a job belongs to exactly one slot.**
 * Slots claim in priority order —
 *
 *   1. early_career  intern / new-grad postings (the scarcest, so it claims first)
 *   2. last_24h      anything first seen inside the last day
 *   3. big_tech      the `big_tech` roster from COMPANY_CATEGORIES
 *
 * — and each later slot only sees what the earlier ones left. Claiming happens
 * AFTER the per-slot cap, so a job that a full slot could not show is still
 * available to the next one.
 *
 * Every slot is additionally bounded to the last 7 days: the section's whole
 * claim is freshness, so a three-week-old internship has no business in it.
 * A slot whose pool comes back empty is not a bug — it is the weekend reality
 * (brief §8), and it carries the honest `emptyText` the UI renders instead.
 *
 * Time comes from the caller's `now` (repo law: no Date.now() in a render path).
 */
import type { Job } from '../../../types';
import { COMPANY_CATEGORIES } from '../companyCategories';

const HOUR = 3_600_000;

/** The section's outer bound — everything shown here is "this week" fresh. */
const FRESH_WINDOW_HOURS = 24 * 7;
/** Slot 2's window, and the only claim its label makes. */
const DAY_WINDOW_HOURS = 24;
/** Past ~4 a slot stops reading as "a couple of fresh ones" and starts nagging. */
export const DEFAULT_MAX_PER_SLOT = 4;

export const TRIPTYCH_SLOT_IDS = ['early_career', 'last_24h', 'big_tech'] as const;
export type TriptychSlotId = (typeof TRIPTYCH_SLOT_IDS)[number];

export interface TriptychSlot {
  id: TriptychSlotId;
  /**
   * The overline above the card. For `early_career` it is DERIVED from what the
   * pool actually holds, so the label can never over-promise internships the
   * slot does not have (see `earlyCareerLabel`).
   */
  label: string;
  /** Quiet copy shown in place of a card when `jobs` is empty. */
  emptyText: string;
  /** Newest-first, capped at `maxPerSlot`, disjoint from the other slots. */
  jobs: Job[];
}

/** Exactly three slots, always, in render order. */
export type TriptychSlots = readonly [TriptychSlot, TriptychSlot, TriptychSlot];

/**
 * The `big_tech` roster, resolved once from the shared taxonomy rather than
 * re-listed here — one source of truth for "who counts as big tech". If that
 * category id is ever renamed the set goes empty and the slot quietly shows its
 * empty state, so `triptychJobs.test.ts` asserts membership against
 * COMPANY_CATEGORIES to make the rename fail loudly in CI instead.
 */
const BIG_TECH_COMPANY_IDS: ReadonlySet<string> = new Set(
  COMPANY_CATEGORIES.find((category) => category.id === 'big_tech')?.companyIds ?? []
);

/** The two levels the first slot speaks for. */
const EARLY_CAREER_LEVELS: ReadonlySet<string> = new Set(['intern', 'new_grad']);

function withinHours(job: Job, now: number, hours: number): boolean {
  return new Date(job.firstSeenAt).getTime() >= now - hours * HOUR;
}

function newestFirst(jobs: Job[]): Job[] {
  return [...jobs].sort(
    (a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime()
  );
}

/**
 * Name the first slot after its actual contents. Interns are scarce, so the
 * pool deliberately includes new-grad roles — but then the label has to say so.
 */
function earlyCareerLabel(pool: Job[]): string {
  if (pool.length === 0) return 'Internships & new grad';
  const hasIntern = pool.some((job) => job.level === 'intern');
  const hasNewGrad = pool.some((job) => job.level === 'new_grad');
  if (!hasNewGrad) return 'Newest internships';
  if (!hasIntern) return 'Newest new-grad roles';
  return 'Internships & new grad';
}

export function selectTriptychSlots(
  jobs: Job[],
  now: number,
  maxPerSlot: number = DEFAULT_MAX_PER_SLOT
): TriptychSlots {
  // Sorted once; every slot filters this list, so every pool is newest-first.
  const fresh = newestFirst(jobs.filter((job) => withinHours(job, now, FRESH_WINDOW_HOURS)));

  const claimed = new Set<string>();
  const claim = (candidates: Job[]): Job[] => {
    const taken = candidates.filter((job) => !claimed.has(job.id)).slice(0, maxPerSlot);
    for (const job of taken) claimed.add(job.id);
    return taken;
  };

  const earlyCareer = claim(fresh.filter((job) => EARLY_CAREER_LEVELS.has(job.level ?? '')));
  const lastDay = claim(fresh.filter((job) => withinHours(job, now, DAY_WINDOW_HOURS)));
  const bigTech = claim(fresh.filter((job) => BIG_TECH_COMPANY_IDS.has(job.company)));

  return [
    {
      id: 'early_career',
      label: earlyCareerLabel(earlyCareer),
      emptyText: 'No internships or new-grad roles this week.',
      jobs: earlyCareer,
    },
    {
      id: 'last_24h',
      label: 'Posted in the last 24 hours',
      emptyText: 'Nothing new in the last day.',
      jobs: lastDay,
    },
    {
      id: 'big_tech',
      label: 'Fresh from big tech',
      emptyText: 'Nothing from big tech this week.',
      jobs: bigTech,
    },
  ];
}
