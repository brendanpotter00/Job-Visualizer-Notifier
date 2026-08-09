/**
 * Selection logic for the fresh-jobs rail, pure for testability.
 *
 * Rule (brief §8): prefer <48h postings from the curated TOP_COMPANY_IDS; when
 * that pool is thin (weekends), widen to 7 days across ALL companies and label
 * the rail honestly ("Fresh this week"). One pill per company (brief §11 —
 * visible duplicates read scrapy), newest first.
 */
import type { Job } from '../../../types';

const HOUR = 3_600_000;

export interface TickerSelection {
  items: Job[];
  /** 'fresh' → "last 48 hours" header; 'week' → "fresh this week" header. */
  mode: 'fresh' | 'week';
}

function newestFirst(jobs: Job[]): Job[] {
  return [...jobs].sort(
    (a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime()
  );
}

function dedupeByCompany(jobs: Job[]): Job[] {
  const seen = new Set<string>();
  return jobs.filter((job) => {
    if (seen.has(job.company)) return false;
    seen.add(job.company);
    return true;
  });
}

export function selectTickerJobs(
  jobs: Job[],
  topCompanyIds: readonly string[],
  now: number,
  maxItems: number
): TickerSelection {
  const topSet = new Set(topCompanyIds);
  const within = (job: Job, hours: number) =>
    new Date(job.firstSeenAt).getTime() >= now - hours * HOUR;

  const fresh = dedupeByCompany(
    newestFirst(jobs.filter((job) => topSet.has(job.company) && within(job, 48)))
  );
  if (fresh.length >= 6) {
    return { items: fresh.slice(0, maxItems), mode: 'fresh' };
  }

  const week = dedupeByCompany(newestFirst(jobs.filter((job) => within(job, 24 * 7))));
  return { items: week.slice(0, maxItems), mode: 'week' };
}
