import type { Job, TimeWindow } from '../../types';
import { TIME_UNITS } from '../../constants/time';

/**
 * Pure math for the Recent page's keyset walk.
 *
 * Kept out of `jobsApi.ts` so the horizon/window rules are unit-testable
 * without an RTK Query store, and so selectors can import them without
 * reaching into the endpoint module.
 */

/**
 * The fetch windows the walk supports.
 *
 * Deliberately a small closed set of *logical* keys rather than raw ISO
 * timestamps: the entry compares windows by this key, so a caller that
 * recomputes "90 days ago" on every scroll tick does NOT look like a window
 * change and does NOT restart the walk. An exact-string ISO comparison would
 * restart forever.
 */
export type JobsWindowKey = '90d' | '180d' | 'all';

/**
 * Default fetch window for the Recent page.
 *
 * Matches the product default — the backend saved-filters service returns
 * `recent=90d` for users with no saved row (`src/backend/CLAUDE.md`), and
 * `recentJobsFiltersSlice` initializes to `'90d'`.
 */
export const RECENT_JOBS_DEFAULT_WINDOW: JobsWindowKey = '90d';

/** Rows requested per company-chunk per page; see `jobsApi.ts` for the sizing rationale. */
export const RECENT_JOBS_PAGE_SIZE = 1000;

const WINDOW_DAYS: Record<JobsWindowKey, number | null> = {
  '90d': 90,
  '180d': 180,
  all: null,
};

/**
 * ISO-8601 UTC (`Z`) lower bound for a window key.
 *
 * `'all'` maps to the epoch rather than to *no* `since`, because `since` is
 * what puts the backend in keyset mode at all — dropping it would silently
 * fall back to the legacy unpaginated path.
 */
export function sinceForWindow(windowKey: JobsWindowKey, now: number = Date.now()): string {
  const days = WINDOW_DAYS[windowKey];
  return days === null
    ? new Date(0).toISOString()
    : new Date(now - days * TIME_UNITS.DAY).toISOString();
}

/**
 * Map a UI time-window filter to the fetch window that covers it.
 *
 * The fetch window only ever needs to *widen* past the 90-day default: every
 * narrower UI window (30d, 7d, 24h…) is already fully contained in the 90-day
 * fetch, so it maps to `'90d'` and needs no refetch at all. Lets ticket 1.4
 * drive the walk straight from the filter slice with no backend knowledge.
 */
export function jobsWindowForTimeWindow(timeWindow: TimeWindow): JobsWindowKey {
  if (timeWindow === 'all') return 'all';
  if (timeWindow === '180d') return '180d';
  return RECENT_JOBS_DEFAULT_WINDOW;
}

/**
 * Cursor/floor bookkeeping key for one chunk: the comma-joined company ids,
 * which is exactly that chunk's request identity. Self-describing, so the
 * chunk's company list is recoverable by splitting the key — deliberately not
 * a chunk index, which would silently re-point if the roster changed.
 */
export function chunkKey(companyIds: string[]): string {
  return companyIds.join(',');
}

/** Inverse of `chunkKey`. */
export function parseChunkKey(key: string): string[] {
  return key.split(',');
}

/**
 * Reserved cursor/floor key for the caller's OWN custom companies.
 *
 * The private half of the feed (`GET /api/users/companies/jobs`) is one more
 * keyset walk running beside the public company-chunks, so it books its cursor
 * and its floor in the SAME `cursors` / `chunkFloors` maps. That is the whole
 * reason it interleaves correctly: `selectHasMoreJobs` and — critically —
 * `computeCompleteHorizon` then account for it with no special casing, so the
 * merged feed is clamped to the depth *both* halves have reached rather than
 * showing custom rows as an unbounded tail below the public horizon.
 *
 * Contains a `:`, which no `COMPANIES` id does, so it can never collide with a
 * `chunkKey()` of real company ids. It is NOT a chunk of company ids, so it must
 * never be handed to `parseChunkKey` + `fetchJobsPage` — `fetchNextJobsPage`
 * filters it out of the public plan explicitly.
 */
export const CUSTOM_JOBS_CHUNK_KEY = 'custom:jobs';

/**
 * Append-dedupe key. Backend rows are keyed by the composite PK
 * `(source_id, id)`, not `id` alone; `company` is included because the cache
 * is partitioned by it. `Job.raw` is typed `unknown`, hence the guarded read.
 */
export function jobKey(job: Job): string {
  const sourceId =
    typeof job.raw === 'object' && job.raw !== null && 'sourceId' in job.raw
      ? String((job.raw as { sourceId: unknown }).sourceId)
      : '';
  return `${sourceId}|${job.company}|${job.id}`;
}

/** Oldest `firstSeenAt` in a page, as an ISO string; `null` for an empty page. */
export function oldestFirstSeenAt(jobs: Job[]): string | null {
  let oldest: string | null = null;
  let oldestMs = Infinity;
  for (const job of jobs) {
    const ms = new Date(job.firstSeenAt).getTime();
    if (Number.isNaN(ms)) continue;
    if (ms < oldestMs) {
      oldestMs = ms;
      oldest = job.firstSeenAt;
    }
  }
  return oldest;
}

/**
 * The provably-complete horizon of the merged multi-chunk result set.
 *
 * **Why this exists.** The batched load is several independent keyset walks,
 * one per company-chunk, each with its own page size. They therefore reach
 * *different depths*: measured on prod, page 1 of the three chunks cut off at
 * 07-30, 07-28 and 07-21. Merging them naively produces a set that is complete
 * down to the shallowest cutoff and increasingly **biased** below it — some
 * companies present, others silently missing, with 24 companies contributing
 * zero rows on first paint. A user scrolling past the shallowest cutoff sees a
 * plausible-looking list that is quietly wrong.
 *
 * The horizon is the deepest point at which *every still-walking chunk* has
 * delivered its rows:
 *
 *   horizon = max over ACTIVE chunks of (oldest first_seen_at fetched for that chunk)
 *
 * - **Active** = the chunk still holds a cursor, i.e. it has more rows below
 *   its current floor. Only those can be *missing* anything.
 * - A chunk whose cursor is exhausted has delivered everything in the window
 *   and does **not** bound the horizon, however shallow its floor is.
 * - All cursors exhausted → `null` (no clamp; the whole set is complete).
 *
 * Rows below the horizon stay cached and surface as later pages push it down.
 *
 * @param cursors     chunkKey -> next cursor, for chunks with more to fetch
 * @param chunkFloors chunkKey -> oldest first_seen_at fetched so far
 * @returns ISO cutoff; rows with `firstSeenAt >= horizon` are complete. `null`
 *          means no clamp.
 */
export function computeCompleteHorizon(
  cursors: Record<string, string> | undefined,
  chunkFloors: Record<string, string> | undefined
): string | null {
  if (!cursors) return null;
  const activeKeys = Object.keys(cursors);
  if (activeKeys.length === 0) return null;

  let horizon: string | null = null;
  let horizonMs = -Infinity;
  for (const key of activeKeys) {
    const floor = chunkFloors?.[key];
    // An active chunk with no floor means "cursor but no rows", which the
    // backend contract makes unreachable (a cursor is emitted only for a FULL
    // page). Treated as non-bounding rather than as +Infinity on purpose: if
    // it ever did happen, clamping everything away would blank the Recent page,
    // which is a strictly worse failure than a slightly-biased tail.
    if (!floor) continue;
    const ms = new Date(floor).getTime();
    if (Number.isNaN(ms)) continue;
    if (ms > horizonMs) {
      horizonMs = ms;
      horizon = floor;
    }
  }
  return horizon;
}

/** Keep only rows at or newer than the horizon. `null` horizon = no clamp. */
export function clampToHorizon(jobs: Job[], horizon: string | null): Job[] {
  if (!horizon) return jobs;
  const horizonMs = new Date(horizon).getTime();
  if (Number.isNaN(horizonMs)) return jobs;
  return jobs.filter((job) => new Date(job.firstSeenAt).getTime() >= horizonMs);
}
