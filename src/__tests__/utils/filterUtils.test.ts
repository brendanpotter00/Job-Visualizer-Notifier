import { describe, it, expect } from 'vitest';
import {
  parseSearchTagInput,
  getArrayDiff,
  sanitizeSearchTag,
} from '../../utils/filterUtils';

describe('filterUtils', () => {
  describe('parseSearchTagInput', () => {
    it('should parse basic input with default include mode', () => {
      const result = parseSearchTagInput('software', 'include');
      expect(result).toEqual({ text: 'software', mode: 'include' });
    });

    it('should parse basic input with default exclude mode', () => {
      const result = parseSearchTagInput('senior', 'exclude');
      expect(result).toEqual({ text: 'senior', mode: 'exclude' });
    });

    it('should detect exclude prefix (-)', () => {
      const result = parseSearchTagInput('-senior', 'include');
      expect(result).toEqual({ text: 'senior', mode: 'exclude' });
    });

    it('should detect include prefix (+)', () => {
      const result = parseSearchTagInput('+backend', 'exclude');
      expect(result).toEqual({ text: 'backend', mode: 'include' });
    });

    it('should handle whitespace around input', () => {
      const result = parseSearchTagInput('  frontend  ', 'include');
      expect(result).toEqual({ text: 'frontend', mode: 'include' });
    });

    it('should handle whitespace after prefix', () => {
      const result = parseSearchTagInput('-  senior', 'include');
      expect(result).toEqual({ text: 'senior', mode: 'exclude' });
    });

    it('should return null for empty string', () => {
      const result = parseSearchTagInput('', 'include');
      expect(result).toBeNull();
    });

    it('should return null for whitespace only', () => {
      const result = parseSearchTagInput('   ', 'include');
      expect(result).toBeNull();
    });

    it('should return null for prefix only (-)', () => {
      const result = parseSearchTagInput('-', 'include');
      expect(result).toBeNull();
    });

    it('should return null for prefix only (+)', () => {
      const result = parseSearchTagInput('+', 'include');
      expect(result).toBeNull();
    });

    it('should return null for prefix with only whitespace', () => {
      const result = parseSearchTagInput('-   ', 'include');
      expect(result).toBeNull();
    });

    it('should handle multi-word input', () => {
      const result = parseSearchTagInput('machine learning', 'include');
      expect(result).toEqual({ text: 'machine learning', mode: 'include' });
    });

    it('should handle multi-word input with prefix', () => {
      const result = parseSearchTagInput('-full stack', 'include');
      expect(result).toEqual({ text: 'full stack', mode: 'exclude' });
    });

    it('should preserve internal spaces', () => {
      const result = parseSearchTagInput('software   engineer', 'include');
      expect(result).toEqual({ text: 'software   engineer', mode: 'include' });
    });
  });

  describe('getArrayDiff', () => {
    it('should detect added elements', () => {
      const oldArray = ['a', 'b'];
      const newArray = ['a', 'b', 'c', 'd'];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual(['c', 'd']);
      expect(result.removed).toEqual([]);
    });

    it('should detect removed elements', () => {
      const oldArray = ['a', 'b', 'c', 'd'];
      const newArray = ['a', 'b'];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual([]);
      expect(result.removed).toEqual(['c', 'd']);
    });

    it('should detect both added and removed elements', () => {
      const oldArray = ['a', 'b', 'c'];
      const newArray = ['b', 'c', 'd'];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual(['d']);
      expect(result.removed).toEqual(['a']);
    });

    it('should handle empty old array', () => {
      const oldArray: string[] = [];
      const newArray = ['a', 'b'];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual(['a', 'b']);
      expect(result.removed).toEqual([]);
    });

    it('should handle empty new array', () => {
      const oldArray = ['a', 'b'];
      const newArray: string[] = [];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual([]);
      expect(result.removed).toEqual(['a', 'b']);
    });

    it('should handle both arrays empty', () => {
      const oldArray: string[] = [];
      const newArray: string[] = [];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual([]);
      expect(result.removed).toEqual([]);
    });

    it('should handle identical arrays', () => {
      const oldArray = ['a', 'b', 'c'];
      const newArray = ['a', 'b', 'c'];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual([]);
      expect(result.removed).toEqual([]);
    });

    it('should work with numbers', () => {
      const oldArray = [1, 2, 3];
      const newArray = [2, 3, 4, 5];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual([4, 5]);
      expect(result.removed).toEqual([1]);
    });

    it('should work with objects (by reference)', () => {
      const obj1 = { id: 1 };
      const obj2 = { id: 2 };
      const obj3 = { id: 3 };

      const oldArray = [obj1, obj2];
      const newArray = [obj2, obj3];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual([obj3]);
      expect(result.removed).toEqual([obj1]);
    });

    it('should handle duplicates in arrays', () => {
      // Sets are used internally for comparison, but duplicates from original arrays are preserved in output
      const oldArray = ['a', 'a', 'b'];
      const newArray = ['b', 'c'];
      const result = getArrayDiff(oldArray, newArray);

      expect(result.added).toEqual(['c']);
      expect(result.removed).toEqual(['a', 'a']); // Both 'a' instances removed
    });
  });

  describe('sanitizeSearchTag', () => {
    it('should return trimmed text', () => {
      const result = sanitizeSearchTag('  software  ');
      expect(result).toBe('software');
    });

    it('should replace multiple spaces with single space', () => {
      const result = sanitizeSearchTag('software   engineer');
      expect(result).toBe('software engineer');
    });

    it('should handle tabs and newlines', () => {
      const result = sanitizeSearchTag('software\t\nengineer');
      expect(result).toBe('software engineer');
    });

    it('should return null for empty string', () => {
      const result = sanitizeSearchTag('');
      expect(result).toBeNull();
    });

    it('should return null for whitespace only', () => {
      const result = sanitizeSearchTag('   ');
      expect(result).toBeNull();
    });

    it('should return null for tabs/newlines only', () => {
      const result = sanitizeSearchTag('\t\n  \t');
      expect(result).toBeNull();
    });

    it('should handle single character', () => {
      const result = sanitizeSearchTag('a');
      expect(result).toBe('a');
    });

    it('should preserve single spaces', () => {
      const result = sanitizeSearchTag('full stack developer');
      expect(result).toBe('full stack developer');
    });

    it('should handle leading and trailing spaces with internal multiple spaces', () => {
      const result = sanitizeSearchTag('  machine    learning  ');
      expect(result).toBe('machine learning');
    });

    it('should handle special characters', () => {
      const result = sanitizeSearchTag('C++ developer');
      expect(result).toBe('C++ developer');
    });

    it('should handle unicode characters', () => {
      const result = sanitizeSearchTag('développeur');
      expect(result).toBe('développeur');
    });
  });
});
