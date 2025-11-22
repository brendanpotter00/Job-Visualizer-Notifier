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

const filtersSlice = createSlice({
  name: 'filters',
  initialState,
  reducers: {
    // Graph filters
    setGraphTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.graph.timeWindow = action.payload;
    },
    setGraphLocation(state, action: PayloadAction<string | undefined>) {
      state.graph.location = action.payload;
    },
    setGraphDepartment(state, action: PayloadAction<string | undefined>) {
      state.graph.department = action.payload;
    },
    setGraphEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.graph.employmentType = action.payload;
    },
    setGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory | 'all'>) {
      state.graph.roleCategory = action.payload;
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
    setListSearchQuery(state, action: PayloadAction<string | undefined>) {
      state.list.searchQuery = action.payload;
    },
    setListLocation(state, action: PayloadAction<string | undefined>) {
      state.list.location = action.payload;
    },
    setListDepartment(state, action: PayloadAction<string | undefined>) {
      state.list.department = action.payload;
    },
    setListEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.list.employmentType = action.payload;
    },
    setListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory | 'all'>) {
      state.list.roleCategory = action.payload;
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
  setGraphLocation,
  setGraphDepartment,
  setGraphEmploymentType,
  setGraphRoleCategory,
  toggleGraphSoftwareOnly,
  resetGraphFilters,
  // List actions
  setListTimeWindow,
  setListSearchQuery,
  setListLocation,
  setListDepartment,
  setListEmploymentType,
  setListRoleCategory,
  toggleListSoftwareOnly,
  resetListFilters,
  // Combined
  resetAllFilters,
} = filtersSlice.actions;

export default filtersSlice.reducer;
