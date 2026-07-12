import type { TimeWindow, TimeBucket, Job } from '../types';
import { format } from 'date-fns';
import { TIME_WINDOW_DURATIONS, BUCKET_SIZES, TIME_UNITS } from '../constants/time';

/**
 * Calculate the 'since' timestamp for a given time window
 */
export function calculateSinceTimestamp(timeWindow: TimeWindow): string {
  if (timeWindow === 'all') {
    return new Date(0).toISOString();
  }

  const now = new Date();
  const durationMs = getTimeWindowDuration(timeWindow);
  const sinceDate = new Date(now.getTime() - durationMs);
  return sinceDate.toISOString();
}

/**
 * Get duration in milliseconds for a time window
 */
export function getTimeWindowDuration(timeWindow: TimeWindow): number {
  return TIME_WINDOW_DURATIONS[timeWindow];
}

/**
 * Get appropriate bucket size for a time window
 */
export function getBucketSize(timeWindow: TimeWindow): number {
  return BUCKET_SIZES[timeWindow];
}

/**
 * Format a bucket label for display
 */
export function formatBucketLabel(bucket: TimeBucket, timeWindow: TimeWindow): string {
  const start = new Date(bucket.bucketStart);

  // For short time windows (up to 24h), show time
  if (['30m', '1h', '3h', '6h', '12h', '24h'].includes(timeWindow)) {
    return format(start, 'HH:mm');
  }

  // For medium windows (3d to 180d), show month and day
  if (['3d', '7d', '14d', '30d', '90d', '180d'].includes(timeWindow)) {
    return format(start, 'MMM d');
  }

  // For the 'all' window, show month and year
  return format(start, 'MMM yyyy');
}

/**
 * Round a date down to the nearest bucket boundary
 */
export function roundToBucketStart(date: Date, bucketSizeMs: number): Date {
  const timestamp = date.getTime();
  const roundedTimestamp = Math.floor(timestamp / bucketSizeMs) * bucketSizeMs;
  return new Date(roundedTimestamp);
}

/**
 * Filter jobs by a time window in hours.
 * Returns jobs FIRST SEEN within the specified number of hours from now.
 *
 * Keyed on `firstSeenAt` (when we first saw the job), matching the recency
 * filter/sort — not the ATS posted date. See `Job.firstSeenAt`.
 *
 * @param jobs - Array of jobs to filter
 * @param hours - Number of hours to look back from now
 * @returns Filtered array of jobs within the time window
 *
 * @example
 * ```typescript
 * const recentJobs = filterJobsByHours(allJobs, 24); // Last 24 hours
 * const veryRecentJobs = filterJobsByHours(allJobs, 3); // Last 3 hours
 * ```
 */
export function filterJobsByHours(jobs: Job[], hours: number): Job[] {
  const cutoffTime = Date.now() - hours * TIME_UNITS.HOUR;
  return jobs.filter((job) => new Date(job.firstSeenAt).getTime() >= cutoffTime);
}

/**
 * Calculate the date range (oldest and newest) for a collection of jobs.
 *
 * Uses `firstSeenAt` (when we first saw each job) so the range matches the
 * activity-over-time buckets it feeds — not the ATS posted date.
 *
 * @param jobs - Array of jobs with firstSeenAt timestamps
 * @returns Object with oldestJobDate and newestJobDate (undefined if no jobs)
 *
 * @example
 * ```typescript
 * const jobs = [
 *   { id: '1', firstSeenAt: '2025-01-01T10:00:00Z', ... },
 *   { id: '2', firstSeenAt: '2025-01-05T15:30:00Z', ... },
 * ];
 * const range = calculateJobDateRange(jobs);
 * // { oldestJobDate: '2025-01-01T10:00:00.000Z', newestJobDate: '2025-01-05T15:30:00.000Z' }
 * ```
 */
export function calculateJobDateRange(jobs: Array<{ firstSeenAt: string }>): {
  oldestJobDate?: string;
  newestJobDate?: string;
} {
  if (jobs.length === 0) {
    return { oldestJobDate: undefined, newestJobDate: undefined };
  }

  const timestamps = jobs.map((job) => new Date(job.firstSeenAt).getTime());
  return {
    oldestJobDate: new Date(Math.min(...timestamps)).toISOString(),
    newestJobDate: new Date(Math.max(...timestamps)).toISOString(),
  };
}
