/**
 * Selection logic for the three-slot fresh-jobs triptych, pure for testability.
 *
 * Three themed slots stand side by side, each flipping through its own small
 * pool. The one rule that makes the row read as three different answers instead
 * of one answer printed three times: **a job belongs to exactly one slot.**
 * Slots claim in priority order —
 *
 *   1. early_career  intern / new-grad postings (the scarcest, so it claims first)
 *   2. last_24h
 *   3. big_tech      the `big_tech` roster from COMPANY_CATEGORIES
 *
 * — and each later slot only sees what the earlier ones left. Claiming happens
 * AFTER the per-slot cap, so a job that a full slot could not show is still
 * available to the next one.
 *
 * A slot whose pool comes back empty is not a bug — it is the weekend reality
 * (brief §8), and it carries the honest `emptyText` the UI renders instead.
 *
 * Time comes from the caller's `now` (repo law: no Date.now() in a render path).
 */
import type { Job } from '../../../types';
import type { SearchJobsBatchRequest } from '../../../features/jobs/searchJobsTypes';
import { COMPANY_CATEGORIES } from '../companyCategories';

const HOUR = 3_600_000;

export const JOBS_PER_SLOT = 5;

const SOFTWARE_ENGINEERING_CATEGORY = 'software_engineering';

export interface SlotWindow {
  hours: number;
  label: string;
}

export const LATEST_WINDOWS: readonly SlotWindow[] = [
  { hours: 24, label: 'Last 24 hours' },
  { hours: 72, label: 'Last 3 days' },
  { hours: 168, label: 'Last week' },
  { hours: 336, label: 'Last 2 weeks' },
  { hours: 720, label: 'Last 30 days' },
];

export const EARLY_CAREER_WINDOWS: readonly SlotWindow[] = [
  { hours: 168, label: 'Last week' },
  { hours: 336, label: 'Last 2 weeks' },
  { hours: 720, label: 'Last 30 days' },
  { hours: 1440, label: 'Last 60 days' },
];

export const BIG_TECH_WINDOWS: readonly SlotWindow[] = [
  { hours: 168, label: 'Last week' },
  { hours: 336, label: 'Last 2 weeks' },
  { hours: 720, label: 'Last 30 days' },
  { hours: 1440, label: 'Last 60 days' },
];

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
  windowHours: number;
  /** Newest-first, disjoint from the other slots. */
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

function capWindow(windows: readonly SlotWindow[]): SlotWindow {
  return windows[windows.length - 1];
}

export const TRIPTYCH_REQUESTS: readonly SearchJobsBatchRequest[] = [
  {
    level: [...EARLY_CAREER_LEVELS],
    category: [SOFTWARE_ENGINEERING_CATEGORY],
    maxAgeHours: capWindow(EARLY_CAREER_WINDOWS).hours,
    limit: JOBS_PER_SLOT,
  },
  {
    category: [SOFTWARE_ENGINEERING_CATEGORY],
    maxAgeHours: capWindow(LATEST_WINDOWS).hours,
    limit: JOBS_PER_SLOT * 2,
  },
  {
    companies: [...BIG_TECH_COMPANY_IDS].sort(),
    category: [SOFTWARE_ENGINEERING_CATEGORY],
    maxAgeHours: capWindow(BIG_TECH_WINDOWS).hours,
    limit: JOBS_PER_SLOT * 3,
  },
];

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
  if (!hasNewGrad) return 'Internships';
  if (!hasIntern) return 'New grad';
  return 'Internships & new grad';
}

function emptyTextFor(windows: readonly SlotWindow[]): string {
  return `None in the ${capWindow(windows).label.toLowerCase()}.`;
}

interface SlotPick {
  jobs: Job[];
  slotWindow: SlotWindow;
}

function pickFromWindows(
  candidates: Job[],
  windows: readonly SlotWindow[],
  now: number,
  perSlot: number
): SlotPick {
  const slotWindow =
    windows.find(
      (candidate) =>
        candidates.filter((job) => withinHours(job, now, candidate.hours)).length >= perSlot
    ) ?? capWindow(windows);
  const pool = candidates.filter((job) => withinHours(job, now, slotWindow.hours));
  return { jobs: pool.slice(0, perSlot), slotWindow };
}

export function selectTriptychSlots(
  jobs: Job[],
  now: number,
  perSlot: number = JOBS_PER_SLOT
): TriptychSlots {
  // Sorted once; every slot filters this list, so every pool is newest-first.
  const engineering = newestFirst(
    jobs.filter((job) => job.category === SOFTWARE_ENGINEERING_CATEGORY)
  );

  const claimed = new Set<string>();
  const claim = (matches: (job: Job) => boolean, windows: readonly SlotWindow[]): SlotPick => {
    const candidates = engineering.filter((job) => !claimed.has(job.id) && matches(job));
    const pick = pickFromWindows(candidates, windows, now, perSlot);
    for (const job of pick.jobs) claimed.add(job.id);
    return pick;
  };

  const earlyCareer = claim(
    (job) => EARLY_CAREER_LEVELS.has(job.level ?? ''),
    EARLY_CAREER_WINDOWS
  );
  const latest = claim(() => true, LATEST_WINDOWS);
  const bigTech = claim((job) => BIG_TECH_COMPANY_IDS.has(job.company), BIG_TECH_WINDOWS);

  return [
    {
      id: 'early_career',
      label: earlyCareerLabel(earlyCareer.jobs),
      emptyText: emptyTextFor(EARLY_CAREER_WINDOWS),
      windowHours: earlyCareer.slotWindow.hours,
      jobs: earlyCareer.jobs,
    },
    {
      id: 'last_24h',
      label: latest.slotWindow.label,
      emptyText: emptyTextFor(LATEST_WINDOWS),
      windowHours: latest.slotWindow.hours,
      jobs: latest.jobs,
    },
    {
      id: 'big_tech',
      label: 'Big tech',
      emptyText: emptyTextFor(BIG_TECH_WINDOWS),
      windowHours: bigTech.slotWindow.hours,
      jobs: bigTech.jobs,
    },
  ];
}
