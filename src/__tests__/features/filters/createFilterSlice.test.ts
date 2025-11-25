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

      expect(actionNames).toHaveLength(23); // 25 actions total
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
        searchTags: [{ pattern: 'engineer', mode: 'include' }],
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
        searchTags: [{ pattern: 'test', mode: 'include' }],
        softwareOnly: true,
        roleCategory: ['frontend' as SoftwareRoleCategory],
      };

      const slice = createFilterSlice('graph', customInitial);
      const state = slice.getInitialState();

      expect(state.filters).toEqual(customInitial);
    });
  });
});
