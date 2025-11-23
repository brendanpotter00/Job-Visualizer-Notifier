import { describe, it, expect } from 'vitest';
import filtersReducer, {
  setGraphTimeWindow,
  addGraphLocation,
  removeGraphLocation,
  clearGraphLocations,
  addGraphSearchTag,
  removeGraphSearchTag,
  toggleGraphSearchTagMode,
  clearGraphSearchTags,
  addGraphDepartment,
  removeGraphDepartment,
  clearGraphDepartments,
  toggleGraphSoftwareOnly,
  addGraphRoleCategory,
  removeGraphRoleCategory,
  clearGraphRoleCategories,
  resetGraphFilters,
  setListTimeWindow,
  addListSearchTag,
  removeListSearchTag,
  toggleListSearchTagMode,
  clearListSearchTags,
  addListLocation,
  removeListLocation,
  clearListLocations,
  addListDepartment,
  removeListDepartment,
  clearListDepartments,
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
      searchTags: undefined,
    },
    list: {
      timeWindow: '30d',
      searchTags: undefined,
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

    it('should add graph search tag with include mode', () => {
      const newState = filtersReducer(initialState, addGraphSearchTag({ text: 'software', mode: 'include' }));

      expect(newState.graph.searchTags).toEqual([{ text: 'software', mode: 'include' }]);
    });

    it('should add graph search tag with exclude mode', () => {
      const newState = filtersReducer(initialState, addGraphSearchTag({ text: 'senior', mode: 'exclude' }));

      expect(newState.graph.searchTags).toEqual([{ text: 'senior', mode: 'exclude' }]);
    });

    it('should add multiple graph search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphSearchTag({ text: 'software', mode: 'include' }));
      state = filtersReducer(state, addGraphSearchTag({ text: 'data', mode: 'include' }));
      state = filtersReducer(state, addGraphSearchTag({ text: 'senior', mode: 'exclude' }));

      expect(state.graph.searchTags).toEqual([
        { text: 'software', mode: 'include' },
        { text: 'data', mode: 'include' },
        { text: 'senior', mode: 'exclude' },
      ]);
    });

    it('should not add duplicate graph search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphSearchTag({ text: 'software', mode: 'include' }));
      state = filtersReducer(state, addGraphSearchTag({ text: 'software', mode: 'include' }));

      expect(state.graph.searchTags).toEqual([{ text: 'software', mode: 'include' }]);
    });

    it('should trim whitespace when adding graph tags', () => {
      const newState = filtersReducer(initialState, addGraphSearchTag({ text: '  software  ', mode: 'include' }));

      expect(newState.graph.searchTags).toEqual([{ text: 'software', mode: 'include' }]);
    });

    it('should ignore empty graph tags', () => {
      const newState = filtersReducer(initialState, addGraphSearchTag({ text: '  ', mode: 'include' }));

      expect(newState.graph.searchTags).toBeUndefined();
    });

    it('should toggle graph search tag mode from include to exclude', () => {
      const stateWithTag: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchTags: [{ text: 'software', mode: 'include' }],
        },
      };

      const newState = filtersReducer(stateWithTag, toggleGraphSearchTagMode('software'));

      expect(newState.graph.searchTags).toEqual([{ text: 'software', mode: 'exclude' }]);
    });

    it('should toggle graph search tag mode from exclude to include', () => {
      const stateWithTag: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchTags: [{ text: 'senior', mode: 'exclude' }],
        },
      };

      const newState = filtersReducer(stateWithTag, toggleGraphSearchTagMode('senior'));

      expect(newState.graph.searchTags).toEqual([{ text: 'senior', mode: 'include' }]);
    });

    it('should do nothing when toggling non-existent tag', () => {
      const stateWithTag: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchTags: [{ text: 'software', mode: 'include' }],
        },
      };

      const newState = filtersReducer(stateWithTag, toggleGraphSearchTagMode('nonexistent'));

      expect(newState.graph.searchTags).toEqual([{ text: 'software', mode: 'include' }]);
    });

    it('should remove graph search tag', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchTags: [
            { text: 'software', mode: 'include' },
            { text: 'data', mode: 'include' },
            { text: 'senior', mode: 'exclude' },
          ],
        },
      };

      const newState = filtersReducer(stateWithTags, removeGraphSearchTag('data'));

      expect(newState.graph.searchTags).toEqual([
        { text: 'software', mode: 'include' },
        { text: 'senior', mode: 'exclude' },
      ]);
    });

    it('should set searchTags to undefined when removing last graph tag', () => {
      const stateWithOneTag: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchTags: [{ text: 'software', mode: 'include' }],
        },
      };

      const newState = filtersReducer(stateWithOneTag, removeGraphSearchTag('software'));

      expect(newState.graph.searchTags).toBeUndefined();
    });

    it('should clear all graph search tags', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          searchTags: [
            { text: 'software', mode: 'include' },
            { text: 'data', mode: 'include' },
            { text: 'senior', mode: 'exclude' },
          ],
        },
      };

      const newState = filtersReducer(stateWithTags, clearGraphSearchTags());

      expect(newState.graph.searchTags).toBeUndefined();
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

    it('should add graph department', () => {
      const newState = filtersReducer(initialState, addGraphDepartment('Engineering'));

      expect(newState.graph.department).toEqual(['Engineering']);
    });

    it('should add multiple graph departments', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphDepartment('Engineering'));
      state = filtersReducer(state, addGraphDepartment('Product'));
      state = filtersReducer(state, addGraphDepartment('Design'));

      expect(state.graph.department).toEqual(['Engineering', 'Product', 'Design']);
    });

    it('should not add duplicate graph departments', () => {
      let state = initialState;
      state = filtersReducer(state, addGraphDepartment('Engineering'));
      state = filtersReducer(state, addGraphDepartment('Engineering'));

      expect(state.graph.department).toEqual(['Engineering']);
    });

    it('should remove graph department', () => {
      const stateWithDepts: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          department: ['Engineering', 'Product', 'Design'],
        },
      };

      const newState = filtersReducer(stateWithDepts, removeGraphDepartment('Product'));

      expect(newState.graph.department).toEqual(['Engineering', 'Design']);
    });

    it('should set department to undefined when removing last graph department', () => {
      const stateWithOneDept: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          department: ['Engineering'],
        },
      };

      const newState = filtersReducer(stateWithOneDept, removeGraphDepartment('Engineering'));

      expect(newState.graph.department).toBeUndefined();
    });

    it('should clear all graph departments', () => {
      const stateWithDepts: FiltersState = {
        ...initialState,
        graph: {
          ...initialState.graph,
          department: ['Engineering', 'Product'],
        },
      };

      const newState = filtersReducer(stateWithDepts, clearGraphDepartments());

      expect(newState.graph.department).toBeUndefined();
    });

    it('should reset graph filters', () => {
      const modifiedState: FiltersState = {
        ...initialState,
        graph: {
          timeWindow: '1h',
          searchTags: [{ text: 'test', mode: 'include' }],
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

    it('should add list search tag with include mode', () => {
      const newState = filtersReducer(initialState, addListSearchTag({ text: 'software', mode: 'include' }));

      expect(newState.list.searchTags).toEqual([{ text: 'software', mode: 'include' }]);
    });

    it('should add list search tag with exclude mode', () => {
      const newState = filtersReducer(initialState, addListSearchTag({ text: 'senior', mode: 'exclude' }));

      expect(newState.list.searchTags).toEqual([{ text: 'senior', mode: 'exclude' }]);
    });

    it('should add multiple list search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addListSearchTag({ text: 'software', mode: 'include' }));
      state = filtersReducer(state, addListSearchTag({ text: 'data', mode: 'include' }));
      state = filtersReducer(state, addListSearchTag({ text: 'senior', mode: 'exclude' }));

      expect(state.list.searchTags).toEqual([
        { text: 'software', mode: 'include' },
        { text: 'data', mode: 'include' },
        { text: 'senior', mode: 'exclude' },
      ]);
    });

    it('should not add duplicate list search tags', () => {
      let state = initialState;
      state = filtersReducer(state, addListSearchTag({ text: 'software', mode: 'include' }));
      state = filtersReducer(state, addListSearchTag({ text: 'software', mode: 'include' }));

      expect(state.list.searchTags).toEqual([{ text: 'software', mode: 'include' }]);
    });

    it('should trim whitespace when adding list tags', () => {
      const newState = filtersReducer(initialState, addListSearchTag({ text: '  software  ', mode: 'include' }));

      expect(newState.list.searchTags).toEqual([{ text: 'software', mode: 'include' }]);
    });

    it('should ignore empty list tags', () => {
      const newState = filtersReducer(initialState, addListSearchTag({ text: '  ', mode: 'include' }));

      expect(newState.list.searchTags).toBeUndefined();
    });

    it('should toggle list search tag mode from include to exclude', () => {
      const stateWithTag: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchTags: [{ text: 'software', mode: 'include' }],
        },
      };

      const newState = filtersReducer(stateWithTag, toggleListSearchTagMode('software'));

      expect(newState.list.searchTags).toEqual([{ text: 'software', mode: 'exclude' }]);
    });

    it('should toggle list search tag mode from exclude to include', () => {
      const stateWithTag: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchTags: [{ text: 'senior', mode: 'exclude' }],
        },
      };

      const newState = filtersReducer(stateWithTag, toggleListSearchTagMode('senior'));

      expect(newState.list.searchTags).toEqual([{ text: 'senior', mode: 'include' }]);
    });

    it('should remove list search tag', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchTags: [
            { text: 'software', mode: 'include' },
            { text: 'data', mode: 'include' },
            { text: 'senior', mode: 'exclude' },
          ],
        },
      };

      const newState = filtersReducer(stateWithTags, removeListSearchTag('data'));

      expect(newState.list.searchTags).toEqual([
        { text: 'software', mode: 'include' },
        { text: 'senior', mode: 'exclude' },
      ]);
    });

    it('should set searchTags to undefined when removing last list tag', () => {
      const stateWithOneTag: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchTags: [{ text: 'software', mode: 'include' }],
        },
      };

      const newState = filtersReducer(stateWithOneTag, removeListSearchTag('software'));

      expect(newState.list.searchTags).toBeUndefined();
    });

    it('should clear all list search tags', () => {
      const stateWithTags: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          searchTags: [
            { text: 'software', mode: 'include' },
            { text: 'data', mode: 'include' },
            { text: 'senior', mode: 'exclude' },
          ],
        },
      };

      const newState = filtersReducer(stateWithTags, clearListSearchTags());

      expect(newState.list.searchTags).toBeUndefined();
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

    it('should add list department', () => {
      const newState = filtersReducer(initialState, addListDepartment('Engineering'));

      expect(newState.list.department).toEqual(['Engineering']);
    });

    it('should add multiple list departments', () => {
      let state = initialState;
      state = filtersReducer(state, addListDepartment('Engineering'));
      state = filtersReducer(state, addListDepartment('Product'));
      state = filtersReducer(state, addListDepartment('Design'));

      expect(state.list.department).toEqual(['Engineering', 'Product', 'Design']);
    });

    it('should not add duplicate list departments', () => {
      let state = initialState;
      state = filtersReducer(state, addListDepartment('Engineering'));
      state = filtersReducer(state, addListDepartment('Engineering'));

      expect(state.list.department).toEqual(['Engineering']);
    });

    it('should remove list department', () => {
      const stateWithDepts: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          department: ['Engineering', 'Product', 'Design'],
        },
      };

      const newState = filtersReducer(stateWithDepts, removeListDepartment('Product'));

      expect(newState.list.department).toEqual(['Engineering', 'Design']);
    });

    it('should set department to undefined when removing last list department', () => {
      const stateWithOneDept: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          department: ['Engineering'],
        },
      };

      const newState = filtersReducer(stateWithOneDept, removeListDepartment('Engineering'));

      expect(newState.list.department).toBeUndefined();
    });

    it('should clear all list departments', () => {
      const stateWithDepts: FiltersState = {
        ...initialState,
        list: {
          ...initialState.list,
          department: ['Engineering', 'Product'],
        },
      };

      const newState = filtersReducer(stateWithDepts, clearListDepartments());

      expect(newState.list.department).toBeUndefined();
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
          searchTags: [{ text: 'test', mode: 'include' }],
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
          searchTags: [{ text: 'test', mode: 'include' }],
          softwareOnly: false,
          roleCategory: ['frontend'],
        },
        list: {
          timeWindow: '7d',
          searchTags: [{ text: 'test', mode: 'include' }],
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
      state = filtersReducer(state, addListSearchTag({ text: 'engineer', mode: 'include' }));

      expect(state.graph.timeWindow).toBe('1h');
      expect(state.graph.location).toEqual(['Remote']);
      expect(state.list.timeWindow).toBe('7d');
      expect(state.list.searchTags).toEqual([{ text: 'engineer', mode: 'include' }]);
    });
  });
});
