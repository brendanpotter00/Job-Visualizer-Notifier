import { describe, it, expect } from 'vitest';
import type { SearchTag, SoftwareRoleCategory } from '../../types';
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
  setDepartments,
  addDepartmentToFilters,
  removeDepartmentFromFilters,
  clearDepartments,
  setRoleCategories,
  addRoleCategoryToFilters,
  removeRoleCategoryFromFilters,
  clearRoleCategories,
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

describe('filterReducerUtils - Departments', () => {
  describe('setDepartments', () => {
    it('should set departments to a specific value', () => {
      const filters = { department: undefined };
      const departments = ['Engineering', 'Product'];

      setDepartments(filters, departments);

      expect(filters.department).toEqual(departments);
    });
  });

  describe('addDepartmentToFilters', () => {
    it('should add a department to empty departments array', () => {
      const filters = { department: undefined };

      addDepartmentToFilters(filters, 'Engineering');

      expect(filters.department).toEqual(['Engineering']);
    });

    it('should add a department to existing departments', () => {
      const filters = { department: ['Engineering'] };

      addDepartmentToFilters(filters, 'Product');

      expect(filters.department).toEqual(['Engineering', 'Product']);
    });

    it('should not add duplicate departments', () => {
      const filters = { department: ['Engineering'] };

      addDepartmentToFilters(filters, 'Engineering');

      expect(filters.department).toHaveLength(1);
    });
  });

  describe('removeDepartmentFromFilters', () => {
    it('should remove a department', () => {
      const filters = { department: ['Engineering', 'Product'] };

      removeDepartmentFromFilters(filters, 'Engineering');

      expect(filters.department).toEqual(['Product']);
    });

    it('should set department to undefined when removing last department', () => {
      const filters = { department: ['Engineering'] };

      removeDepartmentFromFilters(filters, 'Engineering');

      expect(filters.department).toBeUndefined();
    });
  });

  describe('clearDepartments', () => {
    it('should clear all departments', () => {
      const filters = { department: ['Engineering', 'Product'] };

      clearDepartments(filters);

      expect(filters.department).toBeUndefined();
    });
  });
});

describe('filterReducerUtils - Role Categories', () => {
  describe('setRoleCategories', () => {
    it('should set role categories to a specific value', () => {
      const filters = { roleCategory: undefined };
      const categories: SoftwareRoleCategory[] = ['frontend', 'backend'];

      setRoleCategories(filters, categories);

      expect(filters.roleCategory).toEqual(categories);
    });
  });

  describe('addRoleCategoryToFilters', () => {
    it('should add a role category to empty categories array', () => {
      const filters = { roleCategory: undefined };

      addRoleCategoryToFilters(filters, 'frontend');

      expect(filters.roleCategory).toEqual(['frontend']);
    });

    it('should add a role category to existing categories', () => {
      const filters = { roleCategory: ['frontend' as const] };

      addRoleCategoryToFilters(filters, 'backend');

      expect(filters.roleCategory).toEqual(['frontend', 'backend']);
    });

    it('should not add duplicate categories', () => {
      const filters = { roleCategory: ['frontend' as const] };

      addRoleCategoryToFilters(filters, 'frontend');

      expect(filters.roleCategory).toHaveLength(1);
    });
  });

  describe('removeRoleCategoryFromFilters', () => {
    it('should remove a role category', () => {
      const filters = { roleCategory: ['frontend' as const, 'backend' as const] };

      removeRoleCategoryFromFilters(filters, 'frontend');

      expect(filters.roleCategory).toEqual(['backend']);
    });

    it('should set roleCategory to undefined when removing last category', () => {
      const filters = { roleCategory: ['frontend' as const] };

      removeRoleCategoryFromFilters(filters, 'frontend');

      expect(filters.roleCategory).toBeUndefined();
    });
  });

  describe('clearRoleCategories', () => {
    it('should clear all role categories', () => {
      const filters = { roleCategory: ['frontend' as const, 'backend' as const] };

      clearRoleCategories(filters);

      expect(filters.roleCategory).toBeUndefined();
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
});
