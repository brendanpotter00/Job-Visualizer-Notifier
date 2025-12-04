import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useJobMetadata } from '../../../../components/shared/JobCard/useJobMetadata';

/**
 * Tests for useJobMetadata hook
 * Verifies date formatting and memoization behavior
 */
describe('useJobMetadata', () => {
  beforeEach(() => {
    // Mock current time for consistent test results
    vi.setSystemTime(new Date('2025-12-01T12:00:00Z'));
  });

  describe('Date Formatting', () => {
    it('should format date as "X minutes ago" for recent jobs', () => {
      const tenMinutesAgo = '2025-12-01T11:50:00Z';
      const { result } = renderHook(() => useJobMetadata(tenMinutesAgo));

      expect(result.current.postedAgo).toBe('10 minutes ago');
    });

    it('should format date as "about X hours ago" for jobs posted hours ago', () => {
      const threeHoursAgo = '2025-12-01T09:00:00Z';
      const { result } = renderHook(() => useJobMetadata(threeHoursAgo));

      expect(result.current.postedAgo).toBe('about 3 hours ago');
    });

    it('should format date as "X days ago" for jobs posted days ago', () => {
      const twoDaysAgo = '2025-11-29T12:00:00Z';
      const { result } = renderHook(() => useJobMetadata(twoDaysAgo));

      expect(result.current.postedAgo).toBe('2 days ago');
    });

    it('should format date as "2 months ago" for older jobs', () => {
      const twoMonthsAgo = '2025-10-01T12:00:00Z';
      const { result } = renderHook(() => useJobMetadata(twoMonthsAgo));

      expect(result.current.postedAgo).toBe('2 months ago');
    });

    it('should handle "1 minute ago" for very recent jobs', () => {
      const thirtySecondsAgo = '2025-12-01T11:59:30Z';
      const { result } = renderHook(() => useJobMetadata(thirtySecondsAgo));

      expect(result.current.postedAgo).toBe('1 minute ago');
    });
  });

  describe('Memoization', () => {
    it('should return same postedAgo value for same createdAt timestamp', () => {
      const createdAt = '2025-12-01T10:00:00Z';
      const { result, rerender } = renderHook(() => useJobMetadata(createdAt));

      const firstValue = result.current.postedAgo;
      rerender();
      const secondValue = result.current.postedAgo;

      // Should return same formatted string
      expect(firstValue).toBe(secondValue);
      expect(firstValue).toBe('about 2 hours ago');
    });

    it('should return different values when createdAt changes', () => {
      const firstCreatedAt = '2025-12-01T10:00:00Z';
      const secondCreatedAt = '2025-12-01T11:00:00Z';

      const { result, rerender } = renderHook(({ createdAt }) => useJobMetadata(createdAt), {
        initialProps: { createdAt: firstCreatedAt },
      });

      const firstValue = result.current.postedAgo;

      rerender({ createdAt: secondCreatedAt });
      const secondValue = result.current.postedAgo;

      // Different input should produce different output
      expect(firstValue).not.toBe(secondValue);
      expect(firstValue).toBe('about 2 hours ago');
      expect(secondValue).toBe('about 1 hour ago');
    });
  });

  describe('ISO 8601 Timestamp Handling', () => {
    it('should handle timestamps with timezone offset', () => {
      const timestampWithOffset = '2025-12-01T07:00:00-05:00'; // 12:00 UTC
      const { result } = renderHook(() => useJobMetadata(timestampWithOffset));

      expect(result.current.postedAgo).toBe('less than a minute ago');
    });

    it('should handle timestamps without milliseconds', () => {
      const oneHourAgo = '2025-12-01T11:00:00Z';
      const { result } = renderHook(() => useJobMetadata(oneHourAgo));

      expect(result.current.postedAgo).toBe('about 1 hour ago');
    });

    it('should handle timestamps with milliseconds', () => {
      const oneHourAgo = '2025-12-01T11:00:00.000Z';
      const { result } = renderHook(() => useJobMetadata(oneHourAgo));

      expect(result.current.postedAgo).toBe('about 1 hour ago');
    });
  });
});
