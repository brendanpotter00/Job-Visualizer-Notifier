import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { parseWorkdayDate } from '../../utils/workdayDateParser';

describe('workdayDateParser', () => {
  describe('parseWorkdayDate', () => {
    beforeEach(() => {
      // Mock current time for deterministic tests
      vi.useFakeTimers();
      vi.setSystemTime(new Date('2025-11-27T12:00:00Z'));
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    describe('basic date formats', () => {
      it('should parse "Posted Today" to midnight of current day', () => {
        expect(parseWorkdayDate('Posted Today')).toBe('2025-11-27T00:00:00.000Z');
      });

      it('should parse "Posted Yesterday" to midnight of previous day', () => {
        expect(parseWorkdayDate('Posted Yesterday')).toBe('2025-11-26T00:00:00.000Z');
      });

      it('should parse "Posted 1 Day Ago"', () => {
        expect(parseWorkdayDate('Posted 1 Day Ago')).toBe('2025-11-26T00:00:00.000Z');
      });

      it('should parse "Posted 7 Days Ago"', () => {
        expect(parseWorkdayDate('Posted 7 Days Ago')).toBe('2025-11-20T00:00:00.000Z');
      });

      it('should parse "Posted 15 Days Ago"', () => {
        expect(parseWorkdayDate('Posted 15 Days Ago')).toBe('2025-11-12T00:00:00.000Z');
      });

      it('should parse "Posted 30 Days Ago"', () => {
        expect(parseWorkdayDate('Posted 30 Days Ago')).toBe('2025-10-28T00:00:00.000Z');
      });
    });

    describe('plus sign handling (30+)', () => {
      it('should parse "Posted 30+ Days Ago" as 31 days ago', () => {
        expect(parseWorkdayDate('Posted 30+ Days Ago')).toBe('2025-10-27T00:00:00.000Z');
      });

      it('should parse "Posted 1+ Days Ago" as 2 days ago', () => {
        expect(parseWorkdayDate('Posted 1+ Days Ago')).toBe('2025-11-25T00:00:00.000Z');
      });

      it('should parse "Posted 15+ Days Ago" as 16 days ago', () => {
        expect(parseWorkdayDate('Posted 15+ Days Ago')).toBe('2025-11-11T00:00:00.000Z');
      });

      it('should distinguish "30 Days Ago" from "30+ Days Ago"', () => {
        const without = parseWorkdayDate('Posted 30 Days Ago');
        const withPlus = parseWorkdayDate('Posted 30+ Days Ago');
        expect(without).toBe('2025-10-28T00:00:00.000Z'); // 30 days
        expect(withPlus).toBe('2025-10-27T00:00:00.000Z'); // 31 days
        expect(without).not.toBe(withPlus);
      });
    });

    describe('case insensitivity', () => {
      it('should handle uppercase "POSTED TODAY"', () => {
        expect(parseWorkdayDate('POSTED TODAY')).toBe('2025-11-27T00:00:00.000Z');
      });

      it('should handle lowercase "posted yesterday"', () => {
        expect(parseWorkdayDate('posted yesterday')).toBe('2025-11-26T00:00:00.000Z');
      });

      it('should handle mixed case "PoStEd 7 DaYs AgO"', () => {
        expect(parseWorkdayDate('PoStEd 7 DaYs AgO')).toBe('2025-11-20T00:00:00.000Z');
      });
    });

    describe('singular vs plural', () => {
      it('should handle singular "Posted 1 Day Ago"', () => {
        expect(parseWorkdayDate('Posted 1 Day Ago')).toBe('2025-11-26T00:00:00.000Z');
      });

      it('should handle plural "Posted 2 Days Ago"', () => {
        expect(parseWorkdayDate('Posted 2 Days Ago')).toBe('2025-11-25T00:00:00.000Z');
      });
    });

    describe('whitespace handling', () => {
      it('should handle extra whitespace "Posted  30  Days  Ago"', () => {
        expect(parseWorkdayDate('Posted  30  Days  Ago')).toBe('2025-10-28T00:00:00.000Z');
      });
    });

    describe('fallback behavior', () => {
      it('should return current timestamp for undefined', () => {
        const result = parseWorkdayDate(undefined);
        expect(result).toBe('2025-11-27T12:00:00.000Z');
      });

      it('should return current timestamp for empty string', () => {
        const result = parseWorkdayDate('');
        expect(result).toBe('2025-11-27T12:00:00.000Z');
      });

      it('should return current timestamp for invalid string', () => {
        const result = parseWorkdayDate('Not a valid date string');
        expect(result).toBe('2025-11-27T12:00:00.000Z');
      });
    });

    describe('ISO date passthrough', () => {
      it('should parse valid ISO date string', () => {
        const isoDate = '2025-11-20T10:30:00.000Z';
        expect(parseWorkdayDate(isoDate)).toBe(isoDate);
      });

      it('should handle ISO date without milliseconds', () => {
        const result = parseWorkdayDate('2025-11-20T10:30:00Z');
        expect(result).toBe('2025-11-20T10:30:00.000Z');
      });
    });

    describe('edge cases', () => {
      it('should handle "Posted 0 Days Ago" as today', () => {
        expect(parseWorkdayDate('Posted 0 Days Ago')).toBe('2025-11-27T00:00:00.000Z');
      });
    });

    describe('midnight boundary', () => {
      it('should always set time to midnight (00:00:00)', () => {
        const result = parseWorkdayDate('Posted 5 Days Ago');
        expect(result).toMatch(/T00:00:00\.000Z$/);
      });

      it('should set Today to midnight, not current time', () => {
        const result = parseWorkdayDate('Posted Today');
        expect(result).toBe('2025-11-27T00:00:00.000Z');
        expect(result).not.toBe('2025-11-27T12:00:00.000Z'); // not current time
      });
    });
  });
});
