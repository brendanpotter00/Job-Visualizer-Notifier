import type { TimeWindow, TimeBucket } from '../types';
import { format } from 'date-fns';

/**
 * Calculate the 'since' timestamp for a given time window
 */
export function calculateSinceTimestamp(timeWindow: TimeWindow): string {
  const now = new Date();
  const durationMs = getTimeWindowDuration(timeWindow);
  const sinceDate = new Date(now.getTime() - durationMs);
  return sinceDate.toISOString();
}

/**
 * Get duration in milliseconds for a time window
 */
export function getTimeWindowDuration(timeWindow: TimeWindow): number {
  const durations: Record<TimeWindow, number> = {
    '30m': 30 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '3h': 3 * 60 * 60 * 1000,
    '6h': 6 * 60 * 60 * 1000,
    '12h': 12 * 60 * 60 * 1000,
    '24h': 24 * 60 * 60 * 1000,
    '3d': 3 * 24 * 60 * 60 * 1000,
    '7d': 7 * 24 * 60 * 60 * 1000,
    '14d': 14 * 24 * 60 * 60 * 1000,
    '30d': 30 * 24 * 60 * 60 * 1000,
    '90d': 90 * 24 * 60 * 60 * 1000,
    '180d': 180 * 24 * 60 * 60 * 1000,
    '1y': 365 * 24 * 60 * 60 * 1000,
    '2y': 730 * 24 * 60 * 60 * 1000,
  };
  return durations[timeWindow];
}

/**
 * Get appropriate bucket size for a time window
 */
export function getBucketSize(timeWindow: TimeWindow): number {
  const bucketSizes: Record<TimeWindow, number> = {
    '30m': 5 * 60 * 1000, // 5 minutes
    '1h': 10 * 60 * 1000, // 10 minutes
    '3h': 30 * 60 * 1000, // 30 minutes
    '6h': 60 * 60 * 1000, // 1 hour
    '12h': 60 * 60 * 1000, // 1 hour
    '24h': 60 * 60 * 1000, // 1 hour
    '3d': 6 * 60 * 60 * 1000, // 6 hours
    '7d': 24 * 60 * 60 * 1000, // 1 day
    '14d': 12 * 60 * 60 * 1000, // 12 hours
    '30d': 24 * 60 * 60 * 1000, // 1 day
    '90d': 3 * 24 * 60 * 60 * 1000, // 3 days
    '180d': 7 * 24 * 60 * 60 * 1000, // 7 days
    '1y': 14 * 24 * 60 * 60 * 1000, // 14 days
    '2y': 30 * 24 * 60 * 60 * 1000, // 30 days
  };
  return bucketSizes[timeWindow];
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

  // For long windows (1y, 2y), show month and year
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
