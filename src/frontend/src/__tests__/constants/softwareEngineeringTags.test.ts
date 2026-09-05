import { describe, it, expect } from 'vitest';
import type { SearchTag } from '../../types';
import {
  SOFTWARE_ENGINEERING_TAGS,
  isSoftwareEngineeringTag,
  getSoftwareEngineeringTagTexts,
  isSoftwareOnlyEnabled,
} from '../../constants/tags';

describe('softwareEngineeringTags', () => {
  describe('SOFTWARE_ENGINEERING_TAGS constant', () => {
    it('should have 6 predefined tags', () => {
      expect(SOFTWARE_ENGINEERING_TAGS).toHaveLength(6);
    });

    it('should contain expected tag texts', () => {
      const tagTexts = SOFTWARE_ENGINEERING_TAGS.map((t) => t.text);
      expect(tagTexts).toContain('software engineer');
      expect(tagTexts).toContain('developer');
      expect(tagTexts).toContain('engineer');
      expect(tagTexts).toContain('data engineer');
      expect(tagTexts).toContain('backend');
      expect(tagTexts).toContain('frontend');
    });

    it('should have all tags with include mode', () => {
      SOFTWARE_ENGINEERING_TAGS.forEach((tag) => {
        expect(tag.mode).toBe('include');
      });
    });
  });

  describe('isSoftwareEngineeringTag', () => {
    it('should return true for software engineering tags', () => {
      const tag: SearchTag = { text: 'software engineer', mode: 'include' };
      expect(isSoftwareEngineeringTag(tag)).toBe(true);
    });

    it('should return true for all predefined SE tags', () => {
      SOFTWARE_ENGINEERING_TAGS.forEach((tag) => {
        expect(isSoftwareEngineeringTag(tag)).toBe(true);
      });
    });

    it('should return false for non-SE tags', () => {
      const tag: SearchTag = { text: 'manager', mode: 'include' };
      expect(isSoftwareEngineeringTag(tag)).toBe(false);
    });

    it('should return false when mode differs', () => {
      const tag: SearchTag = { text: 'software engineer', mode: 'exclude' };
      expect(isSoftwareEngineeringTag(tag)).toBe(false);
    });
  });

  describe('getSoftwareEngineeringTagTexts', () => {
    it('should return array of tag texts', () => {
      const texts = getSoftwareEngineeringTagTexts();
      expect(texts).toHaveLength(6);
      expect(texts).toContain('software engineer');
      expect(texts).toContain('developer');
    });

    it('should return strings only', () => {
      const texts = getSoftwareEngineeringTagTexts();
      texts.forEach((text) => {
        expect(typeof text).toBe('string');
      });
    });
  });

  describe('isSoftwareOnlyEnabled', () => {
    it('should return false when searchTags is undefined', () => {
      expect(isSoftwareOnlyEnabled(undefined)).toBe(false);
    });

    it('should return false when searchTags is empty array', () => {
      expect(isSoftwareOnlyEnabled([])).toBe(false);
    });

    it('should return true when all SE tags are present with include mode', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'developer', mode: 'include' },
        { text: 'engineer', mode: 'include' },
        { text: 'data engineer', mode: 'include' },
        { text: 'backend', mode: 'include' },
        { text: 'frontend', mode: 'include' },
      ];

      expect(isSoftwareOnlyEnabled(tags)).toBe(true);
    });

    it('should return false when only some SE tags are present', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'developer', mode: 'include' },
      ];

      expect(isSoftwareOnlyEnabled(tags)).toBe(false);
    });

    it('should return false when all SE tags present but one has wrong mode', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'developer', mode: 'include' },
        { text: 'engineer', mode: 'exclude' }, // Wrong mode
        { text: 'data engineer', mode: 'include' },
        { text: 'backend', mode: 'include' },
        { text: 'frontend', mode: 'include' },
      ];

      expect(isSoftwareOnlyEnabled(tags)).toBe(false);
    });

    it('should return true even when additional non-SE tags are present', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'developer', mode: 'include' },
        { text: 'engineer', mode: 'include' },
        { text: 'data engineer', mode: 'include' },
        { text: 'backend', mode: 'include' },
        { text: 'frontend', mode: 'include' },
        { text: 'custom tag', mode: 'include' },
      ];

      expect(isSoftwareOnlyEnabled(tags)).toBe(true);
    });
  });
});
