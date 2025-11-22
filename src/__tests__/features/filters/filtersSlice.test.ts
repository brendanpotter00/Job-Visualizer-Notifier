import { describe, it, expect } from 'vitest';
import filtersReducer, {
  setGraphTimeWindow,
  setGraphLocation,
  toggleGraphSoftwareOnly,
  setGraphRoleCategory,
  resetGraphFilters,
  setListTimeWindow,
  setListSearchQuery,
  toggleListSoftwareOnly,
  resetListFilters,
  resetAllFilters,
} from '../../../features/filters/filtersSlice';
import type { FiltersState } from '../../../features/filters/filtersSlice';

describe('filtersSlice', () => {
  const initialState: FiltersState = {
    graph: {
      timeWindow: '30d',
      softwareOnly: false,
      roleCategory: 'all',
    },
    list: {
      timeWindow: '30d',
      searchQuery: undefined,
      softwareOnly: false,
      roleCategory: 'all',
    },
  };

  describe('graph filters', () => {
    it('should set graph time window', () => {
      const newState = filtersReducer(initialState, setGraphTimeWindow('1h'));

      expect(newState.graph.timeWindow).toBe('1h');
      expect(newState.list.timeWindow).toBe('30d'); // List unchanged
    });

    it('should set graph location', () => {
      const newState = filtersReducer(initialState, setGraphLocation('Los Angeles'));

      expect(newState.graph.location).toBe('Los Angeles');
    });

    it('should toggle graph software only', () => {
      const newState = filtersReducer(initialState, toggleGraphSoftwareOnly());

      expect(newState.graph.softwareOnly).toBe(true);

      const toggledAgain = filtersReducer(newState, toggleGraphSoftwareOnly());
      expect(toggledAgain.graph.softwareOnly).toBe(false);
    });

    it('should set graph role category', () => {
      const newState = filtersReducer(initialState, setGraphRoleCategory('frontend'));

      expect(newState.graph.roleCategory).toBe('frontend');
    });

    it('should reset graph filters', () => {
      const modifiedState: FiltersState = {
        ...initialState,
        graph: {
          timeWindow: '1h',
          softwareOnly: false,
          roleCategory: 'backend',
          location: 'Remote',
        },
      };

      const newState = filtersReducer(modifiedState, resetGraphFilters());

      expect(newState.graph).toEqual(initialState.graph);
      expect(newState.list).toEqual(modifiedState.list); // List unchanged
    });
  });

  describe('list filters', () => {
    it('should set list time window', () => {
      const newState = filtersReducer(initialState, setListTimeWindow('3h'));

      expect(newState.list.timeWindow).toBe('3h');
      expect(newState.graph.timeWindow).toBe('30d'); // Graph unchanged
    });

    it('should set list search query', () => {
      const newState = filtersReducer(initialState, setListSearchQuery('engineer'));

      expect(newState.list.searchQuery).toBe('engineer');
    });

    it('should toggle list software only', () => {
      const newState = filtersReducer(initialState, toggleListSoftwareOnly());

      expect(newState.list.softwareOnly).toBe(true);
    });

    it('should reset list filters', () => {
      const modifiedState: FiltersState = {
        ...initialState,
        list: {
          timeWindow: '7d',
          searchQuery: 'test',
          softwareOnly: false,
          roleCategory: 'qa',
        },
      };

      const newState = filtersReducer(modifiedState, resetListFilters());

      expect(newState.list).toEqual(initialState.list);
      expect(newState.graph).toEqual(modifiedState.graph); // Graph unchanged
    });
  });

  describe('combined actions', () => {
    it('should reset all filters', () => {
      const modifiedState: FiltersState = {
        graph: {
          timeWindow: '1h',
          softwareOnly: false,
          roleCategory: 'frontend',
        },
        list: {
          timeWindow: '7d',
          searchQuery: 'test',
          softwareOnly: false,
          roleCategory: 'backend',
        },
      };

      const newState = filtersReducer(modifiedState, resetAllFilters());

      expect(newState).toEqual(initialState);
    });
  });

  describe('filter independence', () => {
    it('should keep graph and list filters independent', () => {
      let state = initialState;

      // Modify graph
      state = filtersReducer(state, setGraphTimeWindow('1h'));
      state = filtersReducer(state, setGraphLocation('Remote'));

      // Modify list
      state = filtersReducer(state, setListTimeWindow('7d'));
      state = filtersReducer(state, setListSearchQuery('engineer'));

      expect(state.graph.timeWindow).toBe('1h');
      expect(state.graph.location).toBe('Remote');
      expect(state.list.timeWindow).toBe('7d');
      expect(state.list.searchQuery).toBe('engineer');
    });
  });
});
