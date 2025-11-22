import type { Job, TimeBucket, TimeWindow } from '../types';
import { getBucketSize, getTimeWindowDuration, roundToBucketStart } from './dateUtils';

/**
 * Group jobs into time buckets for graph visualization
 */
export function bucketJobsByTime(jobs: Job[], timeWindow: TimeWindow): TimeBucket[] {
  const bucketSizeMs = getBucketSize(timeWindow);
  const windowDurationMs = getTimeWindowDuration(timeWindow);
  const now = new Date();
  const windowStart = new Date(now.getTime() - windowDurationMs);

  // Create map to store jobs by bucket
  const bucketMap = new Map<string, { jobIds: string[]; bucketStart: Date }>();

  // Assign jobs to buckets
  jobs.forEach((job) => {
    const jobDate = new Date(job.createdAt);

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
 * Get cumulative job counts for trend visualization
 */
export function getCumulativeCounts(buckets: TimeBucket[]): number[] {
  let cumulative = 0;
  return buckets.map((bucket) => {
    cumulative += bucket.count;
    return cumulative;
  });
}

/**
 * Calculate summary statistics for bucketed data
 */
export interface BucketStats {
  totalJobs: number;
  maxBucketCount: number;
  avgBucketCount: number;
  bucketsWithJobs: number;
}

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
