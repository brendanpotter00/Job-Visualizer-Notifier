import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { GraphFilters, TimeWindow, SoftwareRoleCategory, SearchTag } from '../../types';
import {
  setSearchTags as setSearchTagsUtil,
  addSearchTagToFilters,
  removeSearchTagFromFilters,
  toggleSearchTagMode as toggleSearchTagModeUtil,
  clearSearchTags as clearSearchTagsUtil,
  setLocations,
  addLocationToFilters,
  removeLocationFromFilters,
  clearLocations as clearLocationsUtil,
  setDepartments,
  addDepartmentToFilters,
  removeDepartmentFromFilters,
  clearDepartments as clearDepartmentsUtil,
  setRoleCategories,
  addRoleCategoryToFilters,
  removeRoleCategoryFromFilters,
  clearRoleCategories as clearRoleCategoriesUtil,
  toggleSoftwareOnlyInFilters,
  setSoftwareOnlyInFilters,
} from '../../utils/filterReducerUtils';

/**
 * Graph filter state
 */
export interface GraphFiltersState {
  filters: GraphFilters;
}

const initialState: GraphFiltersState = {
  filters: {
    timeWindow: '30d',
    searchTags: undefined,
    softwareOnly: false,
    roleCategory: undefined,
  },
};

const graphFiltersSlice = createSlice({
  name: 'graphFilters',
  initialState,
  reducers: {
    // Time window
    setGraphTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.filters.timeWindow = action.payload;
    },

    // Search tags
    setGraphSearchTags(state, action: PayloadAction<SearchTag[] | undefined>) {
      setSearchTagsUtil(state.filters, action.payload);
    },
    addGraphSearchTag(state, action: PayloadAction<SearchTag>) {
      addSearchTagToFilters(state.filters, action.payload);
    },
    removeGraphSearchTag(state, action: PayloadAction<string>) {
      removeSearchTagFromFilters(state.filters, action.payload);
    },
    toggleGraphSearchTagMode(state, action: PayloadAction<string>) {
      toggleSearchTagModeUtil(state.filters, action.payload);
    },
    clearGraphSearchTags(state) {
      clearSearchTagsUtil(state.filters);
    },

    // Location
    setGraphLocation(state, action: PayloadAction<string[] | undefined>) {
      setLocations(state.filters, action.payload);
    },
    addGraphLocation(state, action: PayloadAction<string>) {
      addLocationToFilters(state.filters, action.payload);
    },
    removeGraphLocation(state, action: PayloadAction<string>) {
      removeLocationFromFilters(state.filters, action.payload);
    },
    clearGraphLocations(state) {
      clearLocationsUtil(state.filters);
    },

    // Department
    addGraphDepartment(state, action: PayloadAction<string>) {
      addDepartmentToFilters(state.filters, action.payload);
    },
    removeGraphDepartment(state, action: PayloadAction<string>) {
      removeDepartmentFromFilters(state.filters, action.payload);
    },
    clearGraphDepartments(state) {
      clearDepartmentsUtil(state.filters);
    },
    setGraphDepartment(state, action: PayloadAction<string[] | undefined>) {
      setDepartments(state.filters, action.payload);
    },

    // Employment type
    setGraphEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.filters.employmentType = action.payload;
    },

    // Role category
    addGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      addRoleCategoryToFilters(state.filters, action.payload);
    },
    removeGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      removeRoleCategoryFromFilters(state.filters, action.payload);
    },
    clearGraphRoleCategories(state) {
      clearRoleCategoriesUtil(state.filters);
    },
    setGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory[] | undefined>) {
      setRoleCategories(state.filters, action.payload);
    },

    // Software only - now manages search tags instead of boolean flag
    toggleGraphSoftwareOnly(state) {
      toggleSoftwareOnlyInFilters(state.filters);
    },
    setGraphSoftwareOnly(state, action: PayloadAction<boolean>) {
      setSoftwareOnlyInFilters(state.filters, action.payload);
    },

    // Reset
    resetGraphFilters(state) {
      state.filters = initialState.filters;
    },

    // Sync from list (for cross-slice sync)
    syncGraphFromList(state, action: PayloadAction<GraphFilters>) {
      state.filters = action.payload;
    },
  },
});

export const {
  setGraphTimeWindow,
  setGraphSearchTags,
  addGraphSearchTag,
  removeGraphSearchTag,
  toggleGraphSearchTagMode,
  clearGraphSearchTags,
  setGraphLocation,
  addGraphLocation,
  removeGraphLocation,
  clearGraphLocations,
  addGraphDepartment,
  removeGraphDepartment,
  clearGraphDepartments,
  setGraphDepartment,
  setGraphEmploymentType,
  addGraphRoleCategory,
  removeGraphRoleCategory,
  clearGraphRoleCategories,
  setGraphRoleCategory,
  toggleGraphSoftwareOnly,
  setGraphSoftwareOnly,
  resetGraphFilters,
  syncGraphFromList,
} = graphFiltersSlice.actions;

export default graphFiltersSlice.reducer;
