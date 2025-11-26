import { describe, it, expect } from 'vitest';
import {
  calculateSinceTimestamp,
  getTimeWindowDuration,
  getBucketSize,
  formatBucketLabel,
  roundToBucketStart,
} from '../../utils/dateUtils';
import { TIME_WINDOW_DURATIONS, BUCKET_SIZES, TIME_UNITS } from '../../constants/timeConstants';
import type { TimeWindow, TimeBucket } from '../../types';

describe('dateUtils', () => {
  describe('getTimeWindowDuration', () => {
    it('should return correct duration for 1h window', () => {
      expect(getTimeWindowDuration('1h')).toBe(TIME_UNITS.HOUR);
      expect(getTimeWindowDuration('1h')).toBe(60 * 60 * 1000);
    });

    it('should return correct duration for 24h window', () => {
      expect(getTimeWindowDuration('24h')).toBe(24 * TIME_UNITS.HOUR);
      expect(getTimeWindowDuration('24h')).toBe(24 * 60 * 60 * 1000);
    });

    it('should return correct duration for 7d window', () => {
      expect(getTimeWindowDuration('7d')).toBe(7 * TIME_UNITS.DAY);
      expect(getTimeWindowDuration('7d')).toBe(7 * 24 * 60 * 60 * 1000);
    });

    it('should return correct duration for 30d window', () => {
      expect(getTimeWindowDuration('30d')).toBe(30 * TIME_UNITS.DAY);
    });

    it('should use constants from timeConstants module', () => {
      const allWindows: TimeWindow[] = [
        '30m',
        '1h',
        '3h',
        '6h',
        '12h',
        '24h',
        '3d',
        '7d',
        '14d',
        '30d',
        '90d',
        '180d',
        '1y',
        '2y',
      ];

      allWindows.forEach((window) => {
        expect(getTimeWindowDuration(window)).toBe(TIME_WINDOW_DURATIONS[window]);
      });
    });
  });

  describe('getBucketSize', () => {
    it('should return 5 minutes for 30m window', () => {
      expect(getBucketSize('30m')).toBe(5 * TIME_UNITS.MINUTE);
    });

    it('should return 1 hour for 6h window', () => {
      expect(getBucketSize('6h')).toBe(TIME_UNITS.HOUR);
    });

    it('should return 1 day for 7d window', () => {
      expect(getBucketSize('7d')).toBe(TIME_UNITS.DAY);
    });

    it('should use constants from timeConstants module', () => {
      const allWindows: TimeWindow[] = [
        '30m',
        '1h',
        '3h',
        '6h',
        '12h',
        '24h',
        '3d',
        '7d',
        '14d',
        '30d',
        '90d',
        '180d',
        '1y',
        '2y',
      ];

      allWindows.forEach((window) => {
        expect(getBucketSize(window)).toBe(BUCKET_SIZES[window]);
      });
    });
  });

  describe('calculateSinceTimestamp', () => {
    it('should return ISO 8601 string', () => {
      const result = calculateSinceTimestamp('1h');
      expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    });

    it('should calculate timestamp roughly 1 hour ago', () => {
      const now = new Date();
      const result = calculateSinceTimestamp('1h');
      const since = new Date(result);

      const diff = now.getTime() - since.getTime();
      // Should be close to 1 hour (within 1 second tolerance)
      expect(diff).toBeGreaterThanOrEqual(TIME_UNITS.HOUR - 1000);
      expect(diff).toBeLessThanOrEqual(TIME_UNITS.HOUR + 1000);
    });

    it('should calculate timestamp roughly 7 days ago', () => {
      const now = new Date();
      const result = calculateSinceTimestamp('7d');
      const since = new Date(result);

      const diff = now.getTime() - since.getTime();
      // Should be close to 7 days (within 1 second tolerance)
      expect(diff).toBeGreaterThanOrEqual(7 * TIME_UNITS.DAY - 1000);
      expect(diff).toBeLessThanOrEqual(7 * TIME_UNITS.DAY + 1000);
    });
  });

  describe('formatBucketLabel', () => {
    const createBucket = (isoString: string): TimeBucket => ({
      bucketStart: isoString,
      bucketEnd: isoString,
      count: 0,
      jobIds: [],
    });

    it('should format short time windows with HH:mm', () => {
      const bucket = createBucket('2025-11-26T14:30:00Z');

      // Format uses local timezone, so just check format pattern
      const result = formatBucketLabel(bucket, '30m');
      expect(result).toMatch(/^\d{2}:\d{2}$/);

      // All short windows should use same format
      expect(formatBucketLabel(bucket, '1h')).toMatch(/^\d{2}:\d{2}$/);
      expect(formatBucketLabel(bucket, '6h')).toMatch(/^\d{2}:\d{2}$/);
      expect(formatBucketLabel(bucket, '24h')).toMatch(/^\d{2}:\d{2}$/);
    });

    it('should format medium time windows with MMM d', () => {
      const bucket = createBucket('2025-11-26T14:30:00Z');

      expect(formatBucketLabel(bucket, '3d')).toBe('Nov 26');
      expect(formatBucketLabel(bucket, '7d')).toBe('Nov 26');
      expect(formatBucketLabel(bucket, '30d')).toBe('Nov 26');
      expect(formatBucketLabel(bucket, '90d')).toBe('Nov 26');
    });

    it('should format long time windows with MMM yyyy', () => {
      const bucket = createBucket('2025-11-26T14:30:00Z');

      expect(formatBucketLabel(bucket, '1y')).toBe('Nov 2025');
      expect(formatBucketLabel(bucket, '2y')).toBe('Nov 2025');
    });
  });

  describe('roundToBucketStart', () => {
    it('should round down to bucket boundary', () => {
      const date = new Date('2025-11-26T14:37:42Z');
      const bucketSize = 10 * TIME_UNITS.MINUTE; // 10 minutes

      const rounded = roundToBucketStart(date, bucketSize);

      expect(rounded.toISOString()).toBe('2025-11-26T14:30:00.000Z');
    });

    it('should handle dates already on boundary', () => {
      const date = new Date('2025-11-26T14:30:00Z');
      const bucketSize = 10 * TIME_UNITS.MINUTE;

      const rounded = roundToBucketStart(date, bucketSize);

      expect(rounded.toISOString()).toBe('2025-11-26T14:30:00.000Z');
    });

    it('should work with hour-sized buckets', () => {
      const date = new Date('2025-11-26T14:45:30Z');
      const bucketSize = TIME_UNITS.HOUR;

      const rounded = roundToBucketStart(date, bucketSize);

      expect(rounded.toISOString()).toBe('2025-11-26T14:00:00.000Z');
    });

    it('should work with day-sized buckets', () => {
      const date = new Date('2025-11-26T14:45:30Z');
      const bucketSize = TIME_UNITS.DAY;

      const rounded = roundToBucketStart(date, bucketSize);

      expect(rounded.toISOString()).toBe('2025-11-26T00:00:00.000Z');
    });
  });

  describe('integration with timeConstants', () => {
    it('should use TIME_WINDOW_DURATIONS consistently', () => {
      // Verify all time windows are covered
      const allWindows: TimeWindow[] = Object.keys(TIME_WINDOW_DURATIONS) as TimeWindow[];

      allWindows.forEach((window) => {
        const duration = getTimeWindowDuration(window);
        expect(duration).toBeGreaterThan(0);
        expect(duration).toBe(TIME_WINDOW_DURATIONS[window]);
      });
    });

    it('should use BUCKET_SIZES consistently', () => {
      const allWindows: TimeWindow[] = Object.keys(BUCKET_SIZES) as TimeWindow[];

      allWindows.forEach((window) => {
        const size = getBucketSize(window);
        expect(size).toBeGreaterThan(0);
        expect(size).toBe(BUCKET_SIZES[window]);
      });
    });
  });
});
