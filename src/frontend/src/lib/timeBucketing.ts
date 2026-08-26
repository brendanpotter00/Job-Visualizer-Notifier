import type { Job, TimeBucket, TimeWindow } from '../types';
import {
  calculateJobDateRange,
  getBucketSize,
  getTimeWindowDuration,
  roundToBucketStart,
} from './date';
import { TIME_UNITS } from '../constants/time';

/**
 * Granularity ladder for the 'all time' window, coarsest-last.
 *
 * The first four rungs mirror BUCKET_SIZES for the finite windows and are
 * unchanged. The two above them (quarterly, then the open-ended yearly rung in
 * `pickAllTimeBucketSize`) exist because 'all time' has no upper bound on the
 * span it must draw.
 *
 * **Why this can be a 14-year span.** `firstSeenAt` is the board's own posted
 * date when it publishes one, and that date has no lower bound by design (see
 * `scripts/shared/posted_date.py`) — Palantir currently republishes listings
 * stamped 2012. A single such row drags `windowStart` back a decade while every
 * bit of real activity sits in the last few weeks. At the old flat 30-day
 * ceiling that rendered ~167 buckets: an unreadable hairline with three
 * non-zero points at the right edge.
 *
 * **The fix is coarser buckets, never fewer jobs.** Dropping the old rows would
 * make the chart legible by lying about what we hold; widening the bucket keeps
 * every job on the chart and keeps the bucket count in the same 26–61 band the
 * finite windows already live in.
 */
const ALL_TIME_BUCKET_LADDER: ReadonlyArray<{ maxSpanDays: number; bucketDays: number }> = [
  { maxSpanDays: 30, bucketDays: 1 }, // <=  1 month  -> ~31 buckets
  { maxSpanDays: 180, bucketDays: 7 }, // <=  6 months -> ~27 buckets
  { maxSpanDays: 730, bucketDays: 14 }, // <=  2 years  -> ~53 buckets
  { maxSpanDays: 1825, bucketDays: 30 }, // <=  5 years  -> ~62 buckets
  { maxSpanDays: 3650, bucketDays: 91 }, // <= 10 years  -> ~41 buckets
];

/** The open-ended top rung: one bucket per year beyond 10 years. */
const ALL_TIME_MAX_BUCKET_DAYS = 365;

/**
 * Hard ceiling on how many buckets 'all time' may draw, applied only to the
 * open-ended top rung. Every finite rung above already sits under it; this is
 * the backstop that keeps a pathological span (a job stamped 1970, a clock-skew
 * date) from reintroducing the hairline the ladder was widened to prevent.
 */
const MAX_ALL_TIME_BUCKETS = 64;

/**
 * Pick a bucket size for the 'all time' window based on the span covered by the jobs.
 *
 * Never returns a size that would produce more than {@link MAX_ALL_TIME_BUCKETS}
 * buckets, and never changes the size chosen for spans of 2 years or less — the
 * short-span behaviour that shipped is left exactly as it was.
 */
function pickAllTimeBucketSize(spanMs: number): number {
  for (const rung of ALL_TIME_BUCKET_LADDER) {
    if (spanMs <= rung.maxSpanDays * TIME_UNITS.DAY) {
      return rung.bucketDays * TIME_UNITS.DAY;
    }
  }
  // `bucketJobsByTime` floors `windowStart` onto an epoch-aligned bucket
  // boundary, which can push the start back by up to one whole bucket and so
  // draw one bucket MORE than the span alone implies. Size against
  // MAX - 1 so the ceiling holds after that alignment, not before it.
  const budget = MAX_ALL_TIME_BUCKETS - 1;
  const yearly = ALL_TIME_MAX_BUCKET_DAYS * TIME_UNITS.DAY;
  if (Math.ceil(spanMs / yearly) <= budget) {
    return yearly;
  }
  return Math.ceil(spanMs / budget);
}

/**
 * Groups jobs into time buckets for graph visualization.
 *
 * This function creates empty time buckets for the entire time range to ensure
 * proper graph visualization with consistent X-axis spacing, even when there are
 * gaps in job posting activity.
 *
 * **Algorithm:**
 * 1. Calculate bucket size based on time window (e.g., 24h → 1-hour buckets)
 * 2. Create a map to efficiently store jobs by bucket timestamp
 * 3. Assign each job to its corresponding bucket (rounded to bucket boundary)
 * 4. Generate all buckets in the time range, including empty ones
 * 5. Return sorted array of buckets with job IDs and counts
 *
 * **Time Complexity:** O(n + b) where:
 * - n = number of jobs
 * - b = number of buckets (~30 max for most time windows)
 *
 * **Space Complexity:** O(b) for bucket storage
 *
 * **Important Design Decisions:**
 * - Empty buckets are created for the entire range (critical for proper graph spacing)
 * - Bucket boundaries are aligned to clean intervals (e.g., top of the hour)
 * - Jobs outside the time window are excluded
 * - Each bucket stores job IDs for drill-down functionality
 *
 * @param jobs - Array of jobs to bucket (does not need to be sorted)
 * @param timeWindow - Time window determining bucket size (e.g., '24h', '7d')
 * @returns Array of TimeBucket objects sorted chronologically, including empty buckets
 *
 * Jobs are placed by `firstSeenAt` (when we first saw them), so the chart plots
 * when postings entered our view — not the ATS posted date.
 *
 * @example
 * ```typescript
 * const jobs = [
 *   { id: '1', firstSeenAt: '2025-11-26T10:30:00Z', ... },
 *   { id: '2', firstSeenAt: '2025-11-26T11:45:00Z', ... },
 * ];
 *
 * const buckets = bucketJobsByTime(jobs, '24h');
 * // Returns 24 buckets (1-hour each), most empty, some with job IDs
 * ```
 *
 * @see {@link getBucketSize} for bucket size calculation
 * @see {@link roundToBucketStart} for boundary alignment logic
 * @see docs/architecture.md for detailed algorithm flowchart
 */
export function bucketJobsByTime(jobs: Job[], timeWindow: TimeWindow): TimeBucket[] {
  const now = new Date();
  let bucketSizeMs: number;
  let windowStart: Date;

  if (timeWindow === 'all') {
    if (jobs.length === 0) {
      return [];
    }
    const { oldestJobDate } = calculateJobDateRange(jobs);
    windowStart = new Date(oldestJobDate!);
    bucketSizeMs = pickAllTimeBucketSize(now.getTime() - windowStart.getTime());
  } else {
    bucketSizeMs = getBucketSize(timeWindow);
    const windowDurationMs = getTimeWindowDuration(timeWindow);
    windowStart = new Date(now.getTime() - windowDurationMs);
  }

  // Create map to store jobs by bucket
  const bucketMap = new Map<string, { jobIds: string[]; bucketStart: Date }>();

  // Assign jobs to buckets by when we first saw them (firstSeenAt), matching the
  // recency filter/sort — not the ATS posted date.
  jobs.forEach((job) => {
    const jobDate = new Date(job.firstSeenAt);

    // Skip jobs outside the time window
    if (jobDate < windowStart) {
      return;
    }

    // Round job date to bucket start
    const bucketStart = roundToBucketStart(jobDate, bucketSizeMs);
    const bucketKey = bucketStart.toISOString();

    if (!bucketMap.has(bucketKey)) {
      bucketMap.set(bucketKey, {
        jobIds: [],
        bucketStart,
      });
    }

    bucketMap.get(bucketKey)!.jobIds.push(job.id);
  });

  // Create all buckets (including empty ones)
  const allBuckets: TimeBucket[] = [];
  let currentBucketStart = roundToBucketStart(windowStart, bucketSizeMs);

  while (currentBucketStart < now) {
    const bucketKey = currentBucketStart.toISOString();
    const bucketEnd = new Date(currentBucketStart.getTime() + bucketSizeMs);

    const bucket: TimeBucket = {
      bucketStart: currentBucketStart.toISOString(),
      bucketEnd: bucketEnd.toISOString(),
      count: bucketMap.get(bucketKey)?.jobIds.length || 0,
      jobIds: bucketMap.get(bucketKey)?.jobIds || [],
    };

    allBuckets.push(bucket);
    currentBucketStart = new Date(currentBucketStart.getTime() + bucketSizeMs);
  }

  return allBuckets;
}

/**
 * Calculates cumulative job counts for trend visualization (line graph).
 *
 * This function converts bucket counts into running totals, showing the total
 * number of jobs posted up to each point in time. Essential for displaying
 * cumulative trends rather than per-bucket counts.
 *
 * **Time Complexity:** O(n) where n = number of buckets
 *
 * @param buckets - Array of time buckets with job counts
 * @returns Array of cumulative counts corresponding to each bucket
 *
 * @example
 * ```typescript
 * const buckets = [
 *   { count: 5, ... },  // 5 jobs in bucket 1
 *   { count: 3, ... },  // 3 jobs in bucket 2
 *   { count: 0, ... },  // 0 jobs in bucket 3
 *   { count: 2, ... },  // 2 jobs in bucket 4
 * ];
 *
 * const cumulative = getCumulativeCounts(buckets);
 * // Returns: [5, 8, 8, 10]
 * // Shows running total: 5 → 5+3=8 → 8+0=8 → 8+2=10
 * ```
 */
export function getCumulativeCounts(buckets: TimeBucket[]): number[] {
  let cumulative = 0;
  return buckets.map((bucket) => {
    cumulative += bucket.count;
    return cumulative;
  });
}

/**
 * Summary statistics for bucketed job data.
 *
 * Provides aggregate metrics useful for understanding posting patterns
 * and for UI display purposes.
 */
export interface BucketStats {
  totalJobs: number;
  maxBucketCount: number;
  avgBucketCount: number;
  bucketsWithJobs: number;
}

/**
 * Calculates summary statistics for bucketed job data.
 *
 * Useful for understanding posting patterns at a glance and for
 * displaying aggregate metrics in the UI.
 *
 * **Time Complexity:** O(n) where n = number of buckets
 *
 * @param buckets - Array of time buckets to analyze
 * @returns Statistics object with total, max, average, and non-empty bucket counts
 *
 * @example
 * ```typescript
 * const buckets = [
 *   { count: 10, ... },
 *   { count: 0, ... },
 *   { count: 5, ... },
 *   { count: 0, ... },
 * ];
 *
 * const stats = calculateBucketStats(buckets);
 * // Returns:
 * // {
 * //   totalJobs: 15,
 * //   maxBucketCount: 10,
 * //   avgBucketCount: 7.5,  // 15 / 2 non-empty buckets
 * //   bucketsWithJobs: 2
 * // }
 * ```
 */
export function calculateBucketStats(buckets: TimeBucket[]): BucketStats {
  const totalJobs = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  const maxBucketCount = Math.max(...buckets.map((b) => b.count), 0);
  const bucketsWithJobs = buckets.filter((b) => b.count > 0).length;
  const avgBucketCount = bucketsWithJobs > 0 ? totalJobs / bucketsWithJobs : 0;

  return {
    totalJobs,
    maxBucketCount,
    avgBucketCount,
    bucketsWithJobs,
  };
}
