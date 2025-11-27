import type { TimeWindow, TimeBucket } from '../types';
import { format } from 'date-fns';
import { TIME_WINDOW_DURATIONS, BUCKET_SIZES } from '../constants/timeConstants';

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
