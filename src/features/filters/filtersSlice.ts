import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { GraphFilters, ListFilters, TimeWindow, SoftwareRoleCategory } from '../../types';

/**
 * Filter state (graph and list are independent)
 */
export interface FiltersState {
  graph: GraphFilters;
  list: ListFilters;
}

const initialState: FiltersState = {
  graph: {
    timeWindow: '30d',
    searchQuery: undefined,
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

const filtersSlice = createSlice({
  name: 'filters',
  initialState,
  reducers: {
    // Graph filters
    setGraphTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.graph.timeWindow = action.payload;
    },
    setGraphSearchQuery(state, action: PayloadAction<string[] | undefined>) {
      state.graph.searchQuery = action.payload;
    },
    addGraphSearchTag(state, action: PayloadAction<string>) {
      const tag = action.payload.trim();
      if (!tag) return;

      if (!state.graph.searchQuery) {
        state.graph.searchQuery = [tag];
      } else if (!state.graph.searchQuery.includes(tag)) {
        state.graph.searchQuery.push(tag);
      }
    },
    removeGraphSearchTag(state, action: PayloadAction<string>) {
      if (!state.graph.searchQuery) return;

      state.graph.searchQuery = state.graph.searchQuery.filter(
        tag => tag !== action.payload
      );

      if (state.graph.searchQuery.length === 0) {
        state.graph.searchQuery = undefined;
      }
    },
    clearGraphSearchTags(state) {
      state.graph.searchQuery = undefined;
    },
    setGraphLocation(state, action: PayloadAction<string[] | undefined>) {
      state.graph.location = action.payload;
    },
    addGraphLocation(state, action: PayloadAction<string>) {
      const location = action.payload.trim();
      if (!location) return;

      if (!state.graph.location) {
        state.graph.location = [location];
      } else if (!state.graph.location.includes(location)) {
        state.graph.location.push(location);
      }
    },
    removeGraphLocation(state, action: PayloadAction<string>) {
      if (!state.graph.location) return;

      state.graph.location = state.graph.location.filter(
        loc => loc !== action.payload
      );

      if (state.graph.location.length === 0) {
        state.graph.location = undefined;
      }
    },
    clearGraphLocations(state) {
      state.graph.location = undefined;
    },
    setGraphDepartment(state, action: PayloadAction<string | undefined>) {
      state.graph.department = action.payload;
    },
    setGraphEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.graph.employmentType = action.payload;
    },
    addGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      const category = action.payload;

      if (!state.graph.roleCategory) {
        state.graph.roleCategory = [category];
      } else if (!state.graph.roleCategory.includes(category)) {
        state.graph.roleCategory.push(category);
      }
    },
    removeGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      if (!state.graph.roleCategory) return;

      state.graph.roleCategory = state.graph.roleCategory.filter(
        cat => cat !== action.payload
      );

      if (state.graph.roleCategory.length === 0) {
        state.graph.roleCategory = undefined;
      }
    },
    clearGraphRoleCategories(state) {
      state.graph.roleCategory = undefined;
    },
    toggleGraphSoftwareOnly(state) {
      state.graph.softwareOnly = !state.graph.softwareOnly;
    },
    resetGraphFilters(state) {
      state.graph = initialState.graph;
    },

    // List filters
    setListTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.list.timeWindow = action.payload;
    },
    setListSearchQuery(state, action: PayloadAction<string[] | undefined>) {
      state.list.searchQuery = action.payload;
    },
    addSearchTag(state, action: PayloadAction<string>) {
      const tag = action.payload.trim();
      if (!tag) return;

      if (!state.list.searchQuery) {
        state.list.searchQuery = [tag];
      } else if (!state.list.searchQuery.includes(tag)) {
        state.list.searchQuery.push(tag);
      }
    },
    removeSearchTag(state, action: PayloadAction<string>) {
      if (!state.list.searchQuery) return;

      state.list.searchQuery = state.list.searchQuery.filter(
        tag => tag !== action.payload
      );

      if (state.list.searchQuery.length === 0) {
        state.list.searchQuery = undefined;
      }
    },
    clearSearchTags(state) {
      state.list.searchQuery = undefined;
    },
    setListLocation(state, action: PayloadAction<string[] | undefined>) {
      state.list.location = action.payload;
    },
    addListLocation(state, action: PayloadAction<string>) {
      const location = action.payload.trim();
      if (!location) return;

      if (!state.list.location) {
        state.list.location = [location];
      } else if (!state.list.location.includes(location)) {
        state.list.location.push(location);
      }
    },
    removeListLocation(state, action: PayloadAction<string>) {
      if (!state.list.location) return;

      state.list.location = state.list.location.filter(
        loc => loc !== action.payload
      );

      if (state.list.location.length === 0) {
        state.list.location = undefined;
      }
    },
    clearListLocations(state) {
      state.list.location = undefined;
    },
    setListDepartment(state, action: PayloadAction<string | undefined>) {
      state.list.department = action.payload;
    },
    setListEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.list.employmentType = action.payload;
    },
    addListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      const category = action.payload;

      if (!state.list.roleCategory) {
        state.list.roleCategory = [category];
      } else if (!state.list.roleCategory.includes(category)) {
        state.list.roleCategory.push(category);
      }
    },
    removeListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      if (!state.list.roleCategory) return;

      state.list.roleCategory = state.list.roleCategory.filter(
        cat => cat !== action.payload
      );

      if (state.list.roleCategory.length === 0) {
        state.list.roleCategory = undefined;
      }
    },
    clearListRoleCategories(state) {
      state.list.roleCategory = undefined;
    },
    toggleListSoftwareOnly(state) {
      state.list.softwareOnly = !state.list.softwareOnly;
    },
    resetListFilters(state) {
      state.list = initialState.list;
    },

    // Reset all filters
    resetAllFilters(state) {
      state.graph = initialState.graph;
      state.list = initialState.list;
    },
  },
});

export const {
  // Graph actions
  setGraphTimeWindow,
  setGraphSearchQuery,
  addGraphSearchTag,
  removeGraphSearchTag,
  clearGraphSearchTags,
  setGraphLocation,
  addGraphLocation,
  removeGraphLocation,
  clearGraphLocations,
  setGraphDepartment,
  setGraphEmploymentType,
  addGraphRoleCategory,
  removeGraphRoleCategory,
  clearGraphRoleCategories,
  toggleGraphSoftwareOnly,
  resetGraphFilters,
  // List actions
  setListTimeWindow,
  setListSearchQuery,
  addSearchTag,
  removeSearchTag,
  clearSearchTags,
  setListLocation,
  addListLocation,
  removeListLocation,
  clearListLocations,
  setListDepartment,
  setListEmploymentType,
  addListRoleCategory,
  removeListRoleCategory,
  clearListRoleCategories,
  toggleListSoftwareOnly,
  resetListFilters,
  // Combined
  resetAllFilters,
} = filtersSlice.actions;

export default filtersSlice.reducer;
