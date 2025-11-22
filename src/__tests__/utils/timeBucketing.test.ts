import { describe, it, expect, beforeEach, vi } from 'vitest';
import { bucketJobsByTime, getCumulativeCounts, calculateBucketStats } from '../../utils/timeBucketing';
import type { Job } from '../../types';

describe('timeBucketing', () => {
  // Mock current time for consistent testing
  beforeEach(() => {
    vi.setSystemTime(new Date('2025-11-20T12:00:00Z'));
  });

  const createMockJob = (id: string, createdAt: string): Job => ({
    id,
    source: 'greenhouse',
    company: 'spacex',
    title: 'Software Engineer',
    createdAt,
    url: `https://example.com/job/${id}`,
    classification: {
      isSoftwareAdjacent: true,
      category: 'fullstack',
      confidence: 0.9,
      matchedKeywords: [],
    },
    raw: {},
  });

  describe('bucketJobsByTime', () => {
    it('should create hourly buckets for 24h window', () => {
      const jobs = [
        createMockJob('1', '2025-11-20T10:30:00Z'), // 1.5 hours ago
        createMockJob('2', '2025-11-20T10:45:00Z'), // 1.25 hours ago
        createMockJob('3', '2025-11-20T11:15:00Z'), // 45 min ago
      ];

      const buckets = bucketJobsByTime(jobs, '24h');

      // Should have 24 hourly buckets
      expect(buckets).toHaveLength(24);

      // Find bucket containing first two jobs (10:00-11:00)
      const bucket10 = buckets.find(b =>
        b.bucketStart === '2025-11-20T10:00:00.000Z'
      );
      expect(bucket10?.count).toBe(2);
      expect(bucket10?.jobIds).toHaveLength(2);

      // Find bucket containing third job (11:00-12:00)
      const bucket11 = buckets.find(b =>
        b.bucketStart === '2025-11-20T11:00:00.000Z'
      );
      expect(bucket11?.count).toBe(1);
    });

    it('should create appropriate buckets for 1h window', () => {
      const jobs = [
        createMockJob('1', '2025-11-20T11:30:00Z'), // 30 min ago
        createMockJob('2', '2025-11-20T11:45:00Z'), // 15 min ago
      ];

      const buckets = bucketJobsByTime(jobs, '1h');

      // Should have 6 buckets (10 min each)
      expect(buckets).toHaveLength(6);

      // Jobs should be in appropriate buckets
      const totalJobs = buckets.reduce((sum, b) => sum + b.count, 0);
      expect(totalJobs).toBe(2);
    });

    it('should handle empty job arrays', () => {
      const buckets = bucketJobsByTime([], '24h');

      expect(buckets).toHaveLength(24);
      expect(buckets.every(b => b.count === 0)).toBe(true);
      expect(buckets.every(b => b.jobIds.length === 0)).toBe(true);
    });

    it('should exclude jobs outside the time window', () => {
      const jobs = [
        createMockJob('1', '2025-11-20T11:00:00Z'), // 1 hour ago (included)
        createMockJob('2', '2025-11-18T12:00:00Z'), // 2 days ago (excluded for 24h)
      ];

      const buckets = bucketJobsByTime(jobs, '24h');

      const totalJobs = buckets.reduce((sum, b) => sum + b.count, 0);
      expect(totalJobs).toBe(1); // Only recent job
    });

    it('should correctly set bucket start and end times', () => {
      const jobs = [createMockJob('1', '2025-11-20T11:30:00Z')];

      const buckets = bucketJobsByTime(jobs, '24h');

      buckets.forEach(bucket => {
        const start = new Date(bucket.bucketStart);
        const end = new Date(bucket.bucketEnd);

        // End should be exactly 1 hour after start for 24h window
        expect(end.getTime() - start.getTime()).toBe(60 * 60 * 1000);
      });
    });

    it('should handle jobs at bucket boundaries', () => {
      const jobs = [
        createMockJob('1', '2025-11-20T11:00:00.000Z'), // Exactly on boundary
        createMockJob('2', '2025-11-20T11:59:59.999Z'), // End of same bucket
      ];

      const buckets = bucketJobsByTime(jobs, '24h');

      const bucket11 = buckets.find(b =>
        b.bucketStart === '2025-11-20T11:00:00.000Z'
      );

      expect(bucket11?.count).toBe(2);
    });

    it('should create daily buckets for 7d window', () => {
      const jobs = [
        createMockJob('1', '2025-11-19T12:00:00Z'), // 1 day ago
        createMockJob('2', '2025-11-18T12:00:00Z'), // 2 days ago
      ];

      const buckets = bucketJobsByTime(jobs, '7d');

      // Should have approximately 7-8 daily buckets (depends on exact rounding)
      expect(buckets.length).toBeGreaterThanOrEqual(7);
      expect(buckets.length).toBeLessThanOrEqual(8);

      // Each bucket should span 24 hours
      buckets.forEach(bucket => {
        const start = new Date(bucket.bucketStart);
        const end = new Date(bucket.bucketEnd);
        expect(end.getTime() - start.getTime()).toBe(24 * 60 * 60 * 1000);
      });

      const totalJobs = buckets.reduce((sum, b) => sum + b.count, 0);
      expect(totalJobs).toBe(2);
    });
  });

  describe('getCumulativeCounts', () => {
    it('should calculate cumulative counts', () => {
      const buckets = [
        { bucketStart: '2025-11-20T10:00:00Z', bucketEnd: '2025-11-20T11:00:00Z', count: 2, jobIds: ['1', '2'] },
        { bucketStart: '2025-11-20T11:00:00Z', bucketEnd: '2025-11-20T12:00:00Z', count: 3, jobIds: ['3', '4', '5'] },
        { bucketStart: '2025-11-20T12:00:00Z', bucketEnd: '2025-11-20T13:00:00Z', count: 1, jobIds: ['6'] },
      ];

      const cumulative = getCumulativeCounts(buckets);

      expect(cumulative).toEqual([2, 5, 6]);
    });

    it('should handle empty buckets', () => {
      const buckets = [
        { bucketStart: '2025-11-20T10:00:00Z', bucketEnd: '2025-11-20T11:00:00Z', count: 0, jobIds: [] },
        { bucketStart: '2025-11-20T11:00:00Z', bucketEnd: '2025-11-20T12:00:00Z', count: 5, jobIds: ['1', '2', '3', '4', '5'] },
      ];

      const cumulative = getCumulativeCounts(buckets);

      expect(cumulative).toEqual([0, 5]);
    });
  });

  describe('calculateBucketStats', () => {
    it('should calculate correct statistics', () => {
      const buckets = [
        { bucketStart: '2025-11-20T10:00:00Z', bucketEnd: '2025-11-20T11:00:00Z', count: 2, jobIds: ['1', '2'] },
        { bucketStart: '2025-11-20T11:00:00Z', bucketEnd: '2025-11-20T12:00:00Z', count: 0, jobIds: [] },
        { bucketStart: '2025-11-20T12:00:00Z', bucketEnd: '2025-11-20T13:00:00Z', count: 4, jobIds: ['3', '4', '5', '6'] },
      ];

      const stats = calculateBucketStats(buckets);

      expect(stats.totalJobs).toBe(6);
      expect(stats.maxBucketCount).toBe(4);
      expect(stats.bucketsWithJobs).toBe(2);
      expect(stats.avgBucketCount).toBe(3); // 6 jobs / 2 buckets with jobs
    });

    it('should handle all empty buckets', () => {
      const buckets = [
        { bucketStart: '2025-11-20T10:00:00Z', bucketEnd: '2025-11-20T11:00:00Z', count: 0, jobIds: [] },
        { bucketStart: '2025-11-20T11:00:00Z', bucketEnd: '2025-11-20T12:00:00Z', count: 0, jobIds: [] },
      ];

      const stats = calculateBucketStats(buckets);

      expect(stats.totalJobs).toBe(0);
      expect(stats.maxBucketCount).toBe(0);
      expect(stats.bucketsWithJobs).toBe(0);
      expect(stats.avgBucketCount).toBe(0);
    });
  });
});
