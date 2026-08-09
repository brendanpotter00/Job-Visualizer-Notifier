/**
 * Event-shaped live-activity stats (brief §7 / interview Q7): "SpaceX posted 3
 * jobs in the past 24 hours", "20 jobs tracked in the past 24 hours" — never
 * static vanity metrics. Pure so the exact wording and edge cases are testable.
 */
import type { Job } from '../../../types';
import { getCompanyById } from '../../../config/companies';
import type { LandingStats } from '../types';

export interface ActivityStat {
  /** The big number, pre-formatted (un-rounded where it plausibly can be). */
  value: string;
  /** The rest of the sentence, rendered under/after the value. */
  label: string;
}

const HOUR = 3_600_000;

function jobsWithin(jobs: Job[], hours: number, now: number): Job[] {
  const cutoff = now - hours * HOUR;
  return jobs.filter((job) => new Date(job.firstSeenAt).getTime() >= cutoff);
}

function companyDisplayName(companyId: string): string {
  return getCompanyById(companyId)?.name ?? companyId;
}

/**
 * Build the three-stat strip from the jobs actually on screen so the numbers
 * always cohere with the cards next to them:
 *  1. busiest company in the last 24h (falls back to 7d when the day is quiet),
 *  2. total jobs tracked in the last 24h (falls back to 7d),
 *  3. the measured median-minutes-to-surface claim.
 */
export function computeActivityStats(jobs: Job[], stats: LandingStats, now: number): ActivityStat[] {
  const day = jobsWithin(jobs, 24, now);
  const week = jobsWithin(jobs, 24 * 7, now);
  const window = day.length >= 2 ? day : week;
  const windowLabel = day.length >= 2 ? 'in the past 24 hours' : 'in the past week';

  const byCompany = new Map<string, number>();
  for (const job of window) {
    byCompany.set(job.company, (byCompany.get(job.company) ?? 0) + 1);
  }
  let topCompany: string | null = null;
  let topCount = 0;
  for (const [company, count] of byCompany) {
    if (count > topCount) {
      topCompany = company;
      topCount = count;
    }
  }

  const result: ActivityStat[] = [];
  if (topCompany !== null) {
    result.push({
      value: String(topCount),
      label: `${topCount === 1 ? 'job' : 'jobs'} posted by ${companyDisplayName(topCompany)} ${windowLabel}`,
    });
  }
  result.push({
    value: String(window.length),
    label: `new ${window.length === 1 ? 'job' : 'jobs'} tracked ${windowLabel}`,
  });
  result.push({
    value: `~${stats.medianMinutesToSurface} min`,
    label: 'median from company post to on-site',
  });
  return result;
}
