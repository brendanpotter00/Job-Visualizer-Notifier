import { describe, it, expect } from 'vitest';
import type { SearchTag } from '../../types';
import {
  SOFTWARE_ENGINEERING_TAGS,
  isSoftwareEngineeringTag,
  getSoftwareEngineeringTagTexts,
  isSoftwareOnlyEnabled,
  addAllSoftwareEngineeringTags,
  removeAllSoftwareEngineeringTags,
} from '../../constants/softwareEngineeringTags';

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

  describe('addAllSoftwareEngineeringTags', () => {
    it('should add all SE tags to undefined searchTags', () => {
      const result = addAllSoftwareEngineeringTags(undefined);

      expect(result).toHaveLength(6);
      expect(result).toContainEqual({ text: 'software engineer', mode: 'include' });
      expect(result).toContainEqual({ text: 'developer', mode: 'include' });
      expect(result).toContainEqual({ text: 'engineer', mode: 'include' });
      expect(result).toContainEqual({ text: 'data engineer', mode: 'include' });
      expect(result).toContainEqual({ text: 'backend', mode: 'include' });
      expect(result).toContainEqual({ text: 'frontend', mode: 'include' });
    });

    it('should add all SE tags to empty searchTags array', () => {
      const result = addAllSoftwareEngineeringTags([]);

      expect(result).toHaveLength(6);
    });

    it('should not add duplicate SE tags', () => {
      const existing: SearchTag[] = [{ text: 'software engineer', mode: 'include' }];

      const result = addAllSoftwareEngineeringTags(existing);

      expect(result).toHaveLength(6);
      const seTagCount = result.filter((t) => t.text === 'software engineer').length;
      expect(seTagCount).toBe(1);
    });

    it('should preserve existing non-SE tags', () => {
      const existing: SearchTag[] = [{ text: 'custom tag', mode: 'include' }];

      const result = addAllSoftwareEngineeringTags(existing);

      expect(result).toHaveLength(7); // 6 SE tags + 1 custom tag
      expect(result).toContainEqual({ text: 'custom tag', mode: 'include' });
    });

    it('should preserve existing SE tags and add missing ones', () => {
      const existing: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'developer', mode: 'include' },
      ];

      const result = addAllSoftwareEngineeringTags(existing);

      expect(result).toHaveLength(6);
    });
  });

  describe('removeAllSoftwareEngineeringTags', () => {
    it('should return undefined when searchTags is undefined', () => {
      expect(removeAllSoftwareEngineeringTags(undefined)).toBeUndefined();
    });

    it('should return undefined when searchTags is empty array', () => {
      expect(removeAllSoftwareEngineeringTags([])).toBeUndefined();
    });

    it('should remove all SE tags', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'developer', mode: 'include' },
        { text: 'engineer', mode: 'include' },
        { text: 'data engineer', mode: 'include' },
        { text: 'backend', mode: 'include' },
        { text: 'frontend', mode: 'include' },
      ];

      const result = removeAllSoftwareEngineeringTags(tags);

      expect(result).toBeUndefined();
    });

    it('should preserve non-SE tags', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'custom tag', mode: 'include' },
        { text: 'another tag', mode: 'exclude' },
      ];

      const result = removeAllSoftwareEngineeringTags(tags);

      expect(result).toHaveLength(2);
      expect(result).toContainEqual({ text: 'custom tag', mode: 'include' });
      expect(result).toContainEqual({ text: 'another tag', mode: 'exclude' });
    });

    it('should return undefined when only SE tags exist', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'include' },
        { text: 'developer', mode: 'include' },
      ];

      const result = removeAllSoftwareEngineeringTags(tags);

      expect(result).toBeUndefined();
    });

    it('should handle tags with SE text but different mode', () => {
      const tags: SearchTag[] = [
        { text: 'software engineer', mode: 'exclude' }, // Different mode
        { text: 'custom tag', mode: 'include' },
      ];

      const result = removeAllSoftwareEngineeringTags(tags);

      // Should remove by text, not by mode
      expect(result).toHaveLength(1);
      expect(result).toContainEqual({ text: 'custom tag', mode: 'include' });
    });
  });
});
