import type { TimeWindow } from '../types';

/**
 * Base time units in milliseconds
 * All time calculations should use these constants for consistency
 */
export const TIME_UNITS = {
  MILLISECOND: 1,
  SECOND: 1000,
  MINUTE: 60 * 1000,
  HOUR: 60 * 60 * 1000,
  DAY: 24 * 60 * 60 * 1000,
} as const;

/**
 * Duration in milliseconds for each time window
 * Used for calculating 'since' timestamps and filtering jobs
 */
export const TIME_WINDOW_DURATIONS: Record<TimeWindow, number> = {
  '30m': 30 * TIME_UNITS.MINUTE,
  '1h': TIME_UNITS.HOUR,
  '3h': 3 * TIME_UNITS.HOUR,
  '6h': 6 * TIME_UNITS.HOUR,
  '12h': 12 * TIME_UNITS.HOUR,
  '24h': 24 * TIME_UNITS.HOUR,
  '3d': 3 * TIME_UNITS.DAY,
  '7d': 7 * TIME_UNITS.DAY,
  '14d': 14 * TIME_UNITS.DAY,
  '30d': 30 * TIME_UNITS.DAY,
  '90d': 90 * TIME_UNITS.DAY,
  '180d': 180 * TIME_UNITS.DAY,
  '1y': 365 * TIME_UNITS.DAY,
  '2y': 2 * 365 * TIME_UNITS.DAY,
};

/**
 * Bucket size in milliseconds for each time window
 * Determines the granularity of time-series data bucketing
 *
 * Strategy:
 * - Short windows (≤24h): Minute-level granularity
 * - Medium windows (3d-30d): Hour to day granularity
 * - Long windows (≥90d): Multi-day granularity
 */
export const BUCKET_SIZES: Record<TimeWindow, number> = {
  '30m': 5 * TIME_UNITS.MINUTE, // 5 minutes
  '1h': 10 * TIME_UNITS.MINUTE, // 10 minutes
  '3h': 30 * TIME_UNITS.MINUTE, // 30 minutes
  '6h': TIME_UNITS.HOUR, // 1 hour
  '12h': TIME_UNITS.HOUR, // 1 hour
  '24h': TIME_UNITS.HOUR, // 1 hour
  '3d': 6 * TIME_UNITS.HOUR, // 6 hours
  '7d': TIME_UNITS.DAY, // 1 day
  '14d': 12 * TIME_UNITS.HOUR, // 12 hours
  '30d': TIME_UNITS.DAY, // 1 day
  '90d': 3 * TIME_UNITS.DAY, // 3 days
  '180d': 7 * TIME_UNITS.DAY, // 7 days
  '1y': 14 * TIME_UNITS.DAY, // 14 days
  '2y': 30 * TIME_UNITS.DAY, // 30 days
};
