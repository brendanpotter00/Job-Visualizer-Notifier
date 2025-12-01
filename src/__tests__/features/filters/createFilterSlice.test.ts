import { describe, it, expect } from 'vitest';
import { createFilterSlice } from '../../../features/filters/createFilterSlice';
import type { GraphFilters, ListFilters, TimeWindow, SoftwareRoleCategory } from '../../../types';

describe('createFilterSlice', () => {
  describe('Factory Pattern', () => {
    it('should create a slice with correct name for graph', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);

      expect(slice.name).toBe('graphFilters');
    });

    it('should create a slice with correct name for list', () => {
      const initialFilters: ListFilters = {
        timeWindow: '7d',
        searchTags: undefined,
        softwareOnly: true,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('list', initialFilters);

      expect(slice.name).toBe('listFilters');
    });

    it('should have all expected actions', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const actionNames = Object.keys(slice.actions);

      // Verify all 25 actions exist
      const expectedActions = [
        'setGraphTimeWindow',
        'setGraphSearchTags',
        'addGraphSearchTag',
        'removeGraphSearchTag',
        'toggleGraphSearchTagMode',
        'clearGraphSearchTags',
        'setGraphLocation',
        'addGraphLocation',
        'removeGraphLocation',
        'clearGraphLocations',
        'addGraphDepartment',
        'removeGraphDepartment',
        'clearGraphDepartments',
        'setGraphDepartment',
        'setGraphEmploymentType',
        'addGraphRoleCategory',
        'removeGraphRoleCategory',
        'clearGraphRoleCategories',
        'setGraphRoleCategory',
        'toggleGraphSoftwareOnly',
        'setGraphSoftwareOnly',
        'resetGraphFilters',
        'syncGraphFromList',
      ];

      expectedActions.forEach((actionName) => {
        expect(actionNames).toContain(actionName);
      });

      expect(actionNames).toHaveLength(27); // Total actions (includes additional filter actions)
    });
  });

  describe('Reducer Behavior', () => {
    it('should set time window correctly', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphTimeWindow',
        payload: '7d' as TimeWindow,
      });

      expect(newState.filters.timeWindow).toBe('7d');
    });

    it('should reset filters to initial state', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);

      // Modify state
      let state = { filters: { ...initialFilters, timeWindow: '7d' as TimeWindow } };

      // Reset
      const newState = slice.reducer(state, {
        type: 'graphFilters/resetGraphFilters',
        payload: undefined,
      });

      expect(newState.filters).toEqual(initialFilters);
    });

    it('should handle sync action', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const syncedFilters: GraphFilters = {
        timeWindow: '7d',
        searchTags: [{ text: 'engineer', mode: 'include' }],
        softwareOnly: true,
        roleCategory: ['backend' as SoftwareRoleCategory],
      };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/syncGraphFromList',
        payload: syncedFilters,
      });

      expect(newState.filters).toEqual(syncedFilters);
    });

    it('should set employment type correctly', () => {
      const initialFilters: ListFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('list', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'listFilters/setListEmploymentType',
        payload: 'Full-time',
      });

      expect(newState.filters.employmentType).toBe('Full-time');
    });
  });

  describe('Action Naming Convention', () => {
    it('should capitalize action names correctly for graph', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const actionNames = Object.keys(slice.actions);

      // All actions should start with capital 'G' for Graph
      actionNames.forEach((name) => {
        expect(name).toMatch(/^[a-z]+Graph/);
      });
    });

    it('should capitalize action names correctly for list', () => {
      const initialFilters: ListFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('list', initialFilters);
      const actionNames = Object.keys(slice.actions);

      // All actions should start with capital 'L' for List
      actionNames.forEach((name) => {
        expect(name).toMatch(/^[a-z]+List/);
      });
    });
  });

  describe('Initial State', () => {
    it('should use provided initial filters', () => {
      const customInitial: GraphFilters = {
        timeWindow: '3h',
        searchTags: [{ text: 'test', mode: 'include' }],
        softwareOnly: true,
        roleCategory: ['frontend' as SoftwareRoleCategory],
      };

      const slice = createFilterSlice('graph', customInitial);
      const state = slice.getInitialState();

      expect(state.filters).toEqual(customInitial);
    });
  });

  describe('Search Tag Actions', () => {
    it('should add search tag to undefined array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphSearchTag',
        payload: { text: 'engineer', mode: 'include' as const },
      });

      expect(newState.filters.searchTags).toHaveLength(1);
      expect(newState.filters.searchTags?.[0].text).toBe('engineer');
    });

    it('should add search tag to existing array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'frontend', mode: 'include' }],
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphSearchTag',
        payload: { text: 'backend', mode: 'include' as const },
      });

      expect(newState.filters.searchTags).toHaveLength(2);
      expect(newState.filters.searchTags?.map((t) => t.text)).toEqual(['frontend', 'backend']);
    });

    it('should remove search tag by text', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [
          { text: 'frontend', mode: 'include' },
          { text: 'backend', mode: 'include' },
        ],
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/removeGraphSearchTag',
        payload: 'frontend',
      });

      expect(newState.filters.searchTags).toHaveLength(1);
      expect(newState.filters.searchTags?.[0].text).toBe('backend');
    });

    it('should toggle search tag mode (include <-> exclude)', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'frontend', mode: 'include' }],
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/toggleGraphSearchTagMode',
        payload: 'frontend',
      });

      expect(newState.filters.searchTags?.[0].mode).toBe('exclude');
    });

    it('should clear all search tags (set to undefined)', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [
          { text: 'frontend', mode: 'include' },
          { text: 'backend', mode: 'include' },
        ],
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/clearGraphSearchTags',
        payload: undefined,
      });

      expect(newState.filters.searchTags).toBeUndefined();
    });
  });

  describe('Location Actions', () => {
    it('should add location to filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphLocation',
        payload: 'San Francisco, CA',
      });

      expect(newState.filters.location).toContain('San Francisco, CA');
    });

    it('should remove location from filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
        location: ['San Francisco, CA', 'New York, NY'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/removeGraphLocation',
        payload: 'San Francisco, CA',
      });

      expect(newState.filters.location).toEqual(['New York, NY']);
    });

    it('should clear all locations', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
        location: ['San Francisco, CA', 'New York, NY'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/clearGraphLocations',
        payload: undefined,
      });

      expect(newState.filters.location).toBeUndefined();
    });

    it('should set entire location array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphLocation',
        payload: ['Los Angeles, CA', 'Austin, TX'],
      });

      expect(newState.filters.location).toEqual(['Los Angeles, CA', 'Austin, TX']);
    });
  });

  describe('Department Actions', () => {
    it('should add department to filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphDepartment',
        payload: 'Engineering',
      });

      expect(newState.filters.department).toContain('Engineering');
    });

    it('should remove department from filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
        department: ['Engineering', 'Design'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/removeGraphDepartment',
        payload: 'Engineering',
      });

      expect(newState.filters.department).toEqual(['Design']);
    });

    it('should clear all departments', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
        department: ['Engineering', 'Design'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/clearGraphDepartments',
        payload: undefined,
      });

      expect(newState.filters.department).toBeUndefined();
    });

    it('should set entire department array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphDepartment',
        payload: ['Product', 'Sales'],
      });

      expect(newState.filters.department).toEqual(['Product', 'Sales']);
    });
  });

  describe('Role Category Actions', () => {
    it('should add role category to filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphRoleCategory',
        payload: 'frontend' as SoftwareRoleCategory,
      });

      expect(newState.filters.roleCategory).toContain('frontend');
    });

    it('should remove role category from filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: ['frontend' as SoftwareRoleCategory, 'backend' as SoftwareRoleCategory],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/removeGraphRoleCategory',
        payload: 'frontend' as SoftwareRoleCategory,
      });

      expect(newState.filters.roleCategory).toEqual(['backend']);
    });

    it('should clear all role categories', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: ['frontend' as SoftwareRoleCategory, 'backend' as SoftwareRoleCategory],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/clearGraphRoleCategories',
        payload: undefined,
      });

      expect(newState.filters.roleCategory).toBeUndefined();
    });

    it('should set entire role category array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphRoleCategory',
        payload: ['fullstack' as SoftwareRoleCategory, 'mobile' as SoftwareRoleCategory],
      });

      expect(newState.filters.roleCategory).toEqual(['fullstack', 'mobile']);
    });
  });

  describe('Software Only Actions', () => {
    it('should toggle software only (add/remove SE tags)', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/toggleGraphSoftwareOnly',
        payload: undefined,
      });

      // Software only should add SE tags
      expect(newState.filters.searchTags).toBeDefined();
      expect(newState.filters.searchTags!.length).toBeGreaterThan(0);
    });

    it('should set software only to true', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphSoftwareOnly',
        payload: true,
      });

      expect(newState.filters.searchTags).toBeDefined();
      expect(newState.filters.searchTags!.length).toBeGreaterThan(0);
    });

    it('should set software only to false', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [
          { text: 'software engineer', mode: 'include' },
          { text: 'developer', mode: 'include' },
        ],
        softwareOnly: true,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphSoftwareOnly',
        payload: false,
      });

      // Should remove all SE tags, resulting in undefined
      expect(newState.filters.searchTags).toBeUndefined();
    });
  });

  describe('Edge Cases', () => {
    it('should handle sync with partial filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'test', mode: 'include' }],
        softwareOnly: false,
        roleCategory: ['frontend' as SoftwareRoleCategory],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      const partialFilters: GraphFilters = {
        timeWindow: '7d',
        searchTags: undefined,
        softwareOnly: true,
        roleCategory: undefined,
      };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/syncGraphFromList',
        payload: partialFilters,
      });

      expect(newState.filters.timeWindow).toBe('7d');
      expect(newState.filters.searchTags).toBeUndefined();
      expect(newState.filters.roleCategory).toBeUndefined();
    });

    it('should preserve slice name after reset', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '7d',
        searchTags: [{ text: 'test', mode: 'include' }],
        softwareOnly: true,
        roleCategory: ['frontend' as SoftwareRoleCategory],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const state = { filters: initialFilters };

      slice.reducer(state, {
        type: 'graphFilters/resetGraphFilters',
        payload: undefined,
      });

      // Slice name should still be graphFilters
      expect(slice.name).toBe('graphFilters');
    });

    it('should work with Immer Draft types (Object.assign)', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        roleCategory: undefined,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters };

      // Sync action uses Object.assign for Immer compatibility
      const syncFilters: GraphFilters = {
        timeWindow: '7d',
        searchTags: [{ text: 'test', mode: 'include' }],
        softwareOnly: true,
        roleCategory: ['backend' as SoftwareRoleCategory],
      };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/syncGraphFromList',
        payload: syncFilters,
      });

      // Should successfully assign all properties
      expect(newState.filters).toEqual(syncFilters);
    });
  });
});
