import { describe, it, expect } from 'vitest';
import type { SearchTag } from '../../types';
import { MAX_SEARCH_TAGS } from '../../constants/tags';
import {
  setSearchTags,
  addSearchTagToFilters,
  removeSearchTagFromFilters,
  toggleSearchTagMode,
  clearSearchTags,
  setLocations,
  addLocationToFilters,
  removeLocationFromFilters,
  clearLocations,
  toggleSoftwareOnlyInFilters,
  setSoftwareOnlyInFilters,
} from '../../features/filters/utils/filterReducerUtils';

describe('filterReducerUtils - Search Tags', () => {
  describe('setSearchTags', () => {
    it('should set search tags to a specific value', () => {
      const filters = { searchTags: undefined };
      const tags: SearchTag[] = [{ text: 'javascript', mode: 'include' }];

      setSearchTags(filters, tags);

      expect(filters.searchTags).toEqual(tags);
    });

    it('should set search tags to undefined', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'include' as const }] };

      setSearchTags(filters, undefined);

      expect(filters.searchTags).toBeUndefined();
    });
  });

  describe('addSearchTagToFilters', () => {
    it('should add a search tag to empty tags array', () => {
      const filters = { searchTags: undefined };
      const tag: SearchTag = { text: 'javascript', mode: 'include' };

      addSearchTagToFilters(filters, tag);

      expect(filters.searchTags).toEqual([tag]);
    });

    it('should add a search tag to existing tags', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'include' as const }] };
      const tag: SearchTag = { text: 'python', mode: 'include' };

      addSearchTagToFilters(filters, tag);

      expect(filters.searchTags).toHaveLength(2);
      expect(filters.searchTags).toContainEqual(tag);
    });

    it('should trim whitespace from tag text', () => {
      const filters = { searchTags: undefined };
      const tag: SearchTag = { text: '  javascript  ', mode: 'include' };

      addSearchTagToFilters(filters, tag);

      expect(filters.searchTags).toEqual([{ text: 'javascript', mode: 'include' }]);
    });

    it('refuses to grow the chip set past the search endpoint\'s keyword budget', () => {
      // MAX_SEARCH_TAGS is the endpoint's COMBINED include+exclude budget and the
      // saved-list storage cap, deliberately the same number. Letting the reader
      // build one more chip than that means their next Recent Jobs request is a
      // 400 — and if the chips are saved as a list, every future page load is too,
      // with the page offering nothing but a Retry that reissues the same request.
      const filters = {
        searchTags: Array.from({ length: MAX_SEARCH_TAGS }, (_, n) => ({
          text: `tag-${n}`,
          mode: 'include' as const,
        })),
      };

      addSearchTagToFilters(filters, { text: 'one-too-many', mode: 'include' });

      expect(filters.searchTags).toHaveLength(MAX_SEARCH_TAGS);
      expect(filters.searchTags.map((t) => t.text)).not.toContain('one-too-many');
    });

    it('should not add empty tag after trimming', () => {
      const filters = { searchTags: undefined };
      const tag: SearchTag = { text: '   ', mode: 'include' };

      addSearchTagToFilters(filters, tag);

      expect(filters.searchTags).toBeUndefined();
    });

    it('should not add duplicate tags', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'include' as const }] };
      const tag: SearchTag = { text: 'javascript', mode: 'include' };

      addSearchTagToFilters(filters, tag);

      expect(filters.searchTags).toHaveLength(1);
    });

    it('should preserve tag mode when adding', () => {
      const filters = { searchTags: undefined };
      const tag: SearchTag = { text: 'javascript', mode: 'exclude' };

      addSearchTagToFilters(filters, tag);

      expect(filters.searchTags).toEqual([{ text: 'javascript', mode: 'exclude' }]);
    });
  });

  describe('removeSearchTagFromFilters', () => {
    it('should remove a search tag by text', () => {
      const filters = {
        searchTags: [
          { text: 'javascript', mode: 'include' as const },
          { text: 'python', mode: 'include' as const },
        ],
      };

      removeSearchTagFromFilters(filters, 'javascript');

      expect(filters.searchTags).toEqual([{ text: 'python', mode: 'include' }]);
    });

    it('should set tags to undefined when removing last tag', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'include' as const }] };

      removeSearchTagFromFilters(filters, 'javascript');

      expect(filters.searchTags).toBeUndefined();
    });

    it('should do nothing if tags are undefined', () => {
      const filters = { searchTags: undefined };

      removeSearchTagFromFilters(filters, 'javascript');

      expect(filters.searchTags).toBeUndefined();
    });

    it('should do nothing if tag does not exist', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'include' as const }] };

      removeSearchTagFromFilters(filters, 'python');

      expect(filters.searchTags).toHaveLength(1);
      expect(filters.searchTags).toEqual([{ text: 'javascript', mode: 'include' }]);
    });
  });

  describe('toggleSearchTagMode', () => {
    it('should toggle tag mode from include to exclude', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'include' as const }] };

      toggleSearchTagMode(filters, 'javascript');

      expect(filters.searchTags?.[0].mode).toBe('exclude');
    });

    it('should toggle tag mode from exclude to include', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'exclude' as const }] };

      toggleSearchTagMode(filters, 'javascript');

      expect(filters.searchTags?.[0].mode).toBe('include');
    });

    it('should do nothing if tags are undefined', () => {
      const filters = { searchTags: undefined };

      toggleSearchTagMode(filters, 'javascript');

      expect(filters.searchTags).toBeUndefined();
    });

    it('should do nothing if tag does not exist', () => {
      const filters = { searchTags: [{ text: 'javascript', mode: 'include' as const }] };

      toggleSearchTagMode(filters, 'python');

      expect(filters.searchTags?.[0].mode).toBe('include');
    });
  });

  describe('clearSearchTags', () => {
    it('should clear all search tags', () => {
      const filters = {
        searchTags: [
          { text: 'javascript', mode: 'include' as const },
          { text: 'python', mode: 'include' as const },
        ],
      };

      clearSearchTags(filters);

      expect(filters.searchTags).toBeUndefined();
    });
  });
});

describe('filterReducerUtils - Locations', () => {
  describe('setLocations', () => {
    it('should set locations to a specific value', () => {
      const filters = { location: undefined };
      const locations = ['San Francisco', 'New York'];

      setLocations(filters, locations);

      expect(filters.location).toEqual(locations);
    });

    it('should set locations to undefined', () => {
      const filters = { location: ['San Francisco'] };

      setLocations(filters, undefined);

      expect(filters.location).toBeUndefined();
    });
  });

  describe('addLocationToFilters', () => {
    it('should add a location to empty locations array', () => {
      const filters = { location: undefined };

      addLocationToFilters(filters, 'San Francisco');

      expect(filters.location).toEqual(['San Francisco']);
    });

    it('should add a location to existing locations', () => {
      const filters = { location: ['San Francisco'] };

      addLocationToFilters(filters, 'New York');

      expect(filters.location).toEqual(['San Francisco', 'New York']);
    });

    it('should trim whitespace from location', () => {
      const filters = { location: undefined };

      addLocationToFilters(filters, '  San Francisco  ');

      expect(filters.location).toEqual(['San Francisco']);
    });

    it('should not add empty location after trimming', () => {
      const filters = { location: undefined };

      addLocationToFilters(filters, '   ');

      expect(filters.location).toBeUndefined();
    });

    it('should not add duplicate locations', () => {
      const filters = { location: ['San Francisco'] };

      addLocationToFilters(filters, 'San Francisco');

      expect(filters.location).toHaveLength(1);
    });
  });

  describe('removeLocationFromFilters', () => {
    it('should remove a location', () => {
      const filters = { location: ['San Francisco', 'New York'] };

      removeLocationFromFilters(filters, 'San Francisco');

      expect(filters.location).toEqual(['New York']);
    });

    it('should set location to undefined when removing last location', () => {
      const filters = { location: ['San Francisco'] };

      removeLocationFromFilters(filters, 'San Francisco');

      expect(filters.location).toBeUndefined();
    });

    it('should do nothing if location is undefined', () => {
      const filters = { location: undefined };

      removeLocationFromFilters(filters, 'San Francisco');

      expect(filters.location).toBeUndefined();
    });
  });

  describe('clearLocations', () => {
    it('should clear all locations', () => {
      const filters = { location: ['San Francisco', 'New York'] };

      clearLocations(filters);

      expect(filters.location).toBeUndefined();
    });
  });
});

describe('filterReducerUtils - Software Only', () => {
  describe('toggleSoftwareOnlyInFilters', () => {
    it('should add all SE tags when none are present', () => {
      const filters = { searchTags: undefined, softwareOnly: false };

      toggleSoftwareOnlyInFilters(filters);

      expect(filters.searchTags).toHaveLength(6);
      expect(filters.softwareOnly).toBe(true);
      expect(filters.searchTags).toContainEqual({ text: 'software engineer', mode: 'include' });
      expect(filters.searchTags).toContainEqual({ text: 'developer', mode: 'include' });
      expect(filters.searchTags).toContainEqual({ text: 'engineer', mode: 'include' });
      expect(filters.searchTags).toContainEqual({ text: 'data engineer', mode: 'include' });
      expect(filters.searchTags).toContainEqual({ text: 'backend', mode: 'include' });
      expect(filters.searchTags).toContainEqual({ text: 'frontend', mode: 'include' });
    });

    it('should remove all SE tags when all are present', () => {
      const filters = {
        searchTags: [
          { text: 'software engineer', mode: 'include' as const },
          { text: 'developer', mode: 'include' as const },
          { text: 'engineer', mode: 'include' as const },
          { text: 'data engineer', mode: 'include' as const },
          { text: 'backend', mode: 'include' as const },
          { text: 'frontend', mode: 'include' as const },
        ],
        softwareOnly: true,
      };

      toggleSoftwareOnlyInFilters(filters);

      expect(filters.searchTags).toBeUndefined();
      expect(filters.softwareOnly).toBe(false);
    });

    it('should preserve non-SE tags when removing SE tags', () => {
      const filters = {
        searchTags: [
          { text: 'software engineer', mode: 'include' as const },
          { text: 'developer', mode: 'include' as const },
          { text: 'engineer', mode: 'include' as const },
          { text: 'data engineer', mode: 'include' as const },
          { text: 'backend', mode: 'include' as const },
          { text: 'frontend', mode: 'include' as const },
          { text: 'custom tag', mode: 'include' as const },
        ],
        softwareOnly: true,
      };

      toggleSoftwareOnlyInFilters(filters);

      expect(filters.searchTags).toEqual([{ text: 'custom tag', mode: 'include' }]);
      expect(filters.softwareOnly).toBe(false);
    });

    it('should not add duplicate SE tags', () => {
      const filters = {
        searchTags: [{ text: 'software engineer', mode: 'include' as const }],
        softwareOnly: false,
      };

      toggleSoftwareOnlyInFilters(filters);

      const seTagCounts = filters.searchTags?.filter((t) => t.text === 'software engineer').length;
      expect(seTagCounts).toBe(1);
    });

    it('should add all SE tags when some are present', () => {
      const filters = {
        searchTags: [{ text: 'software engineer', mode: 'include' as const }],
        softwareOnly: false,
      };

      toggleSoftwareOnlyInFilters(filters);

      expect(filters.searchTags).toHaveLength(6);
      expect(filters.softwareOnly).toBe(true);
    });
  });

  describe('setSoftwareOnlyInFilters', () => {
    it('should add all SE tags when set to true', () => {
      const filters = { searchTags: undefined, softwareOnly: false };

      setSoftwareOnlyInFilters(filters, true);

      expect(filters.searchTags).toHaveLength(6);
      expect(filters.softwareOnly).toBe(true);
    });

    it('should remove all SE tags when set to false', () => {
      const filters = {
        searchTags: [
          { text: 'software engineer', mode: 'include' as const },
          { text: 'developer', mode: 'include' as const },
          { text: 'engineer', mode: 'include' as const },
          { text: 'data engineer', mode: 'include' as const },
          { text: 'backend', mode: 'include' as const },
          { text: 'frontend', mode: 'include' as const },
        ],
        softwareOnly: true,
      };

      setSoftwareOnlyInFilters(filters, false);

      expect(filters.searchTags).toBeUndefined();
      expect(filters.softwareOnly).toBe(false);
    });

    it('should preserve non-SE tags when set to false', () => {
      const filters = {
        searchTags: [
          { text: 'software engineer', mode: 'include' as const },
          { text: 'custom tag', mode: 'include' as const },
        ],
        softwareOnly: true,
      };

      setSoftwareOnlyInFilters(filters, false);

      expect(filters.searchTags).toEqual([{ text: 'custom tag', mode: 'include' }]);
    });

    it('should not add duplicate SE tags when set to true', () => {
      const filters = {
        searchTags: [{ text: 'developer', mode: 'include' as const }],
        softwareOnly: false,
      };

      setSoftwareOnlyInFilters(filters, true);

      const devTagCounts = filters.searchTags?.filter((t) => t.text === 'developer').length;
      expect(devTagCounts).toBe(1);
      expect(filters.searchTags).toHaveLength(6);
    });
  });

  describe('the keyword budget applies to the bulk helpers too', () => {
    // Both helpers append up to six tags in ONE action, so the per-add guard in
    // `addSearchTagToFilters` never sees them. Twenty existing chips plus this
    // toggle is twenty-six keywords, which is a hard 400 on every subsequent
    // Recent Jobs request — and the page's only affordance is a Retry that
    // reissues the rejected request.
    const nearlyFull = () =>
      Array.from({ length: MAX_SEARCH_TAGS - 2 }, (_, n) => ({
        text: `tag-${n}`,
        mode: 'include' as const,
      }));

    it('toggleSoftwareOnlyInFilters stops at the cap instead of overflowing it', () => {
      const filters = { searchTags: nearlyFull(), softwareOnly: false };

      toggleSoftwareOnlyInFilters(filters);

      expect(filters.searchTags).toHaveLength(MAX_SEARCH_TAGS);
    });

    it('setSoftwareOnlyInFilters stops at the cap instead of overflowing it', () => {
      const filters = { searchTags: nearlyFull(), softwareOnly: false };

      setSoftwareOnlyInFilters(filters, true);

      expect(filters.searchTags).toHaveLength(MAX_SEARCH_TAGS);
    });

    it('never truncates chips the reader already has', () => {
      // Appending "only into the remaining room" — not slicing the merged list.
      // A saved list stored before the cap existed still reads back oversized
      // (KeywordListResponse carries no max_length), and silently deleting chips
      // that are visible on screen is the failure mode the ADD-site caps exist to
      // avoid.
      const existing = Array.from({ length: MAX_SEARCH_TAGS + 3 }, (_, n) => ({
        text: `legacy-${n}`,
        mode: 'include' as const,
      }));
      const filters = { searchTags: [...existing], softwareOnly: false };

      setSoftwareOnlyInFilters(filters, true);

      expect(filters.searchTags).toEqual(existing);
    });
  });
});
