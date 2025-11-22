import { describe, it, expect } from 'vitest';
import filtersReducer, {
  setGraphTimeWindow,
  addGraphLocation,
  removeGraphLocation,
  clearGraphLocations,
  addGraphSearchTag,
  removeGraphSearchTag,
  clearGraphSearchTags,
  toggleGraphSoftwareOnly,
  addGraphRoleCategory,
  removeGraphRoleCategory,
  clearGraphRoleCategories,
  resetGraphFilters,
  setListTimeWindow,
  setListSearchQuery,
  addSearchTag,
  removeSearchTag,
  clearSearchTags,
  addListLocation,
  removeListLocation,
  clearListLocations,
  addListRoleCategory,
  removeListRoleCategory,
  clearListRoleCategories,
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
      roleCategory: undefined,
    },
    list: {
      timeWindow: '30d',
      searchQuery: undefined,
      softwareOnly: false,
      roleCategory: undefined,
    },
  };

  describe('graph filters', () => {
    it('should set graph time window', () => {
      const newState = filtersReducer(initialState, setGraphTimeWindow('1h'));

      expect(newState.graph.timeWindow).toBe('1h');
      expect(newState.list.timeWindow).toBe('30d'); // List unchanged
    });


    it('should toggle graph software only', () => {
      const newState = filtersReducer(initialState, toggleGraphSoftwareOnly());

      expect(newState.graph.softwareOnly).toBe(true);

      const toggledAgain = filtersReducer(newState, toggleGraphSoftwareOnly());
      expect(toggledAgain.graph.softwareOnly).toBe(false);
    });

    it('should add graph role category', () => {
      const newState = filtersReducer(initialState, addGraphRoleCategory('frontend'));

      expect(newState.graph.roleCategory).toEqual(['frontend']);
    });

    it('should add multiple graph role categories', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphRoleCategory('frontend'));
      state = filtersReducer(state, addGraphRoleCategory('backend'));
      state = filtersReducer(state, addGraphRoleCategory('fullstack'));

      expect(state.graph.roleCategory).toEqual(['frontend', 'backend', 'fullstack']);
    });

    it('should not add duplicate graph role categories', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphRoleCategory('frontend'));
      state = filtersReducer(state, addGraphRoleCategory('frontend'));

      expect(state.graph.roleCategory).toEqual(['frontend']);
    });

    it('should remove graph role category', () => {
      const stateWithCats: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          roleCategory: ['frontend', 'backend', 'fullstack'],
        },
      };

      const newState = filtersReducer(stateWithCats, removeGraphRoleCategory('backend'));

      expect(newState.graph.roleCategory).toEqual(['frontend', 'fullstack']);
    });

    it('should set roleCategory to undefined when removing last graph category', () => {
      const stateWithOneCat: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          roleCategory: ['frontend'],
        },
      };

      const newState = filtersReducer(stateWithOneCat, removeGraphRoleCategory('frontend'));

      expect(newState.graph.roleCategory).toBeUndefined();
    });

    it('should clear all graph role categories', () => {
      const stateWithCats: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          roleCategory: ['frontend', 'backend'],
        },
      };

      const newState = filtersReducer(stateWithCats, clearGraphRoleCategories());

      expect(newState.graph.roleCategory).toBeUndefined();
    });

    it('should add graph search tag', () => {
      const newState = filtersReducer(initialState, addGraphSearchTag('software'));

      expect(newState.graph.searchQuery).toEqual(['software']);
    });

    it('should add multiple graph search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphSearchTag('software'));
      state = filtersReducer(state, addGraphSearchTag('data'));
      state = filtersReducer(state, addGraphSearchTag('backend'));

      expect(state.graph.searchQuery).toEqual(['software', 'data', 'backend']);
    });

    it('should not add duplicate graph search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphSearchTag('software'));
      state = filtersReducer(state, addGraphSearchTag('software'));

      expect(state.graph.searchQuery).toEqual(['software']);
    });

    it('should trim whitespace when adding graph tags', () => {
      const newState = filtersReducer(initialState, addGraphSearchTag('  software  '));

      expect(newState.graph.searchQuery).toEqual(['software']);
    });

    it('should ignore empty graph tags', () => {
      const newState = filtersReducer(initialState, addGraphSearchTag('  '));

      expect(newState.graph.searchQuery).toBeUndefined();
    });

    it('should remove graph search tag', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchQuery: ['software', 'data', 'backend'],
        },
      };

      const newState = filtersReducer(stateWithTags, removeGraphSearchTag('data'));

      expect(newState.graph.searchQuery).toEqual(['software', 'backend']);
    });

    it('should set searchQuery to undefined when removing last graph tag', () => {
      const stateWithOneTag: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchQuery: ['software'],
        },
      };

      const newState = filtersReducer(stateWithOneTag, removeGraphSearchTag('software'));

      expect(newState.graph.searchQuery).toBeUndefined();
    });

    it('should clear all graph search tags', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchQuery: ['software', 'data', 'backend'],
        },
      };

      const newState = filtersReducer(stateWithTags, clearGraphSearchTags());

      expect(newState.graph.searchQuery).toBeUndefined();
    });

    it('should add graph location', () => {
      const newState = filtersReducer(initialState, addGraphLocation('San Francisco, CA'));

      expect(newState.graph.location).toEqual(['San Francisco, CA']);
    });

    it('should add multiple graph locations', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphLocation('United States'));
      state = filtersReducer(state, addGraphLocation('San Francisco, CA'));
      state = filtersReducer(state, addGraphLocation('New York, NY'));

      expect(state.graph.location).toEqual(['United States', 'San Francisco, CA', 'New York, NY']);
    });

    it('should not add duplicate graph locations', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphLocation('San Francisco, CA'));
      state = filtersReducer(state, addGraphLocation('San Francisco, CA'));

      expect(state.graph.location).toEqual(['San Francisco, CA']);
    });

    it('should remove graph location', () => {
      const stateWithLocs: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          location: ['United States', 'San Francisco, CA', 'New York, NY'],
        },
      };

      const newState = filtersReducer(stateWithLocs, removeGraphLocation('San Francisco, CA'));

      expect(newState.graph.location).toEqual(['United States', 'New York, NY']);
    });

    it('should set location to undefined when removing last graph location', () => {
      const stateWithOneLoc: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          location: ['San Francisco, CA'],
        },
      };

      const newState = filtersReducer(stateWithOneLoc, removeGraphLocation('San Francisco, CA'));

      expect(newState.graph.location).toBeUndefined();
    });

    it('should clear all graph locations', () => {
      const stateWithLocs: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          location: ['United States', 'San Francisco, CA'],
        },
      };

      const newState = filtersReducer(stateWithLocs, clearGraphLocations());

      expect(newState.graph.location).toBeUndefined();
    });

    it('should reset graph filters', () => {
      const modifiedState: FiltersState = {
        ...initialState,
        graph: {
          timeWindow: '1h',
          searchQuery: ['test'],
          location: ['United States', 'Remote'],
          softwareOnly: false,
          roleCategory: ['backend'],
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
      const newState = filtersReducer(initialState, setListSearchQuery(['engineer']));

      expect(newState.list.searchQuery).toEqual(['engineer']);
    });

    it('should add search tag', () => {
      const newState = filtersReducer(initialState, addSearchTag('software'));

      expect(newState.list.searchQuery).toEqual(['software']);
    });

    it('should add multiple search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addSearchTag('software'));
      state = filtersReducer(state, addSearchTag('data'));
      state = filtersReducer(state, addSearchTag('backend'));

      expect(state.list.searchQuery).toEqual(['software', 'data', 'backend']);
    });

    it('should not add duplicate search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addSearchTag('software'));
      state = filtersReducer(state, addSearchTag('software'));

      expect(state.list.searchQuery).toEqual(['software']);
    });

    it('should trim whitespace when adding tags', () => {
      const newState = filtersReducer(initialState, addSearchTag('  software  '));

      expect(newState.list.searchQuery).toEqual(['software']);
    });

    it('should ignore empty tags', () => {
      const newState = filtersReducer(initialState, addSearchTag('  '));

      expect(newState.list.searchQuery).toBeUndefined();
    });

    it('should remove search tag', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchQuery: ['software', 'data', 'backend'],
        },
      };

      const newState = filtersReducer(stateWithTags, removeSearchTag('data'));

      expect(newState.list.searchQuery).toEqual(['software', 'backend']);
    });

    it('should set searchQuery to undefined when removing last tag', () => {
      const stateWithOneTag: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchQuery: ['software'],
        },
      };

      const newState = filtersReducer(stateWithOneTag, removeSearchTag('software'));

      expect(newState.list.searchQuery).toBeUndefined();
    });

    it('should clear all search tags', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchQuery: ['software', 'data', 'backend'],
        },
      };

      const newState = filtersReducer(stateWithTags, clearSearchTags());

      expect(newState.list.searchQuery).toBeUndefined();
    });

    it('should add list location', () => {
      const newState = filtersReducer(initialState, addListLocation('San Francisco, CA'));

      expect(newState.list.location).toEqual(['San Francisco, CA']);
    });

    it('should add multiple list locations', () => {
      let state = initialState;
      state = filtersReducer(state, addListLocation('United States'));
      state = filtersReducer(state, addListLocation('San Francisco, CA'));

      expect(state.list.location).toEqual(['United States', 'San Francisco, CA']);
    });

    it('should remove list location', () => {
      const stateWithLocs: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          location: ['United States', 'San Francisco, CA'],
        },
      };

      const newState = filtersReducer(stateWithLocs, removeListLocation('United States'));

      expect(newState.list.location).toEqual(['San Francisco, CA']);
    });

    it('should clear all list locations', () => {
      const stateWithLocs: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          location: ['United States', 'San Francisco, CA'],
        },
      };

      const newState = filtersReducer(stateWithLocs, clearListLocations());

      expect(newState.list.location).toBeUndefined();
    });

    it('should toggle list software only', () => {
      const newState = filtersReducer(initialState, toggleListSoftwareOnly());

      expect(newState.list.softwareOnly).toBe(true);
    });

    it('should add list role category', () => {
      const newState = filtersReducer(initialState, addListRoleCategory('frontend'));

      expect(newState.list.roleCategory).toEqual(['frontend']);
    });

    it('should add multiple list role categories', () => {
      let state = initialState;
      state = filtersReducer(state, addListRoleCategory('frontend'));
      state = filtersReducer(state, addListRoleCategory('backend'));
      state = filtersReducer(state, addListRoleCategory('fullstack'));

      expect(state.list.roleCategory).toEqual(['frontend', 'backend', 'fullstack']);
    });

    it('should not add duplicate list role categories', () => {
      let state = initialState;
      state = filtersReducer(state, addListRoleCategory('frontend'));
      state = filtersReducer(state, addListRoleCategory('frontend'));

      expect(state.list.roleCategory).toEqual(['frontend']);
    });

    it('should remove list role category', () => {
      const stateWithCats: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          roleCategory: ['frontend', 'backend', 'fullstack'],
        },
      };

      const newState = filtersReducer(stateWithCats, removeListRoleCategory('backend'));

      expect(newState.list.roleCategory).toEqual(['frontend', 'fullstack']);
    });

    it('should set roleCategory to undefined when removing last list category', () => {
      const stateWithOneCat: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          roleCategory: ['frontend'],
        },
      };

      const newState = filtersReducer(stateWithOneCat, removeListRoleCategory('frontend'));

      expect(newState.list.roleCategory).toBeUndefined();
    });

    it('should clear all list role categories', () => {
      const stateWithCats: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          roleCategory: ['frontend', 'backend'],
        },
      };

      const newState = filtersReducer(stateWithCats, clearListRoleCategories());

      expect(newState.list.roleCategory).toBeUndefined();
    });

    it('should reset list filters', () => {
      const modifiedState: FiltersState = {
        ...initialState,
        list: {
          timeWindow: '7d',
          searchQuery: ['test'],
          softwareOnly: false,
          roleCategory: ['qa'],
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
          roleCategory: ['frontend'],
        },
        list: {
          timeWindow: '7d',
          searchQuery: ['test'],
          softwareOnly: false,
          roleCategory: ['backend'],
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
      state = filtersReducer(state, addGraphLocation('Remote'));

      // Modify list
      state = filtersReducer(state, setListTimeWindow('7d'));
      state = filtersReducer(state, addSearchTag('engineer'));

      expect(state.graph.timeWindow).toBe('1h');
      expect(state.graph.location).toEqual(['Remote']);
      expect(state.list.timeWindow).toBe('7d');
      expect(state.list.searchQuery).toEqual(['engineer']);
    });
  });
});
