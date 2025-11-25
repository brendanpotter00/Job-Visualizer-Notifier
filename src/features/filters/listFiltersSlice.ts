import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { ListFilters, TimeWindow, SoftwareRoleCategory, SearchTag } from '../../types';
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
 * List filter state
 */
export interface ListFiltersState {
  filters: ListFilters;
}

const initialState: ListFiltersState = {
  filters: {
    timeWindow: '30d',
    searchTags: undefined,
    softwareOnly: false,
    roleCategory: undefined,
  },
};

const listFiltersSlice = createSlice({
  name: 'listFilters',
  initialState,
  reducers: {
    // Time window
    setListTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.filters.timeWindow = action.payload;
    },

    // Search tags
    setListSearchTags(state, action: PayloadAction<SearchTag[] | undefined>) {
      setSearchTagsUtil(state.filters, action.payload);
    },
    addListSearchTag(state, action: PayloadAction<SearchTag>) {
      addSearchTagToFilters(state.filters, action.payload);
    },
    removeListSearchTag(state, action: PayloadAction<string>) {
      removeSearchTagFromFilters(state.filters, action.payload);
    },
    toggleListSearchTagMode(state, action: PayloadAction<string>) {
      toggleSearchTagModeUtil(state.filters, action.payload);
    },
    clearListSearchTags(state) {
      clearSearchTagsUtil(state.filters);
    },

    // Location
    setListLocation(state, action: PayloadAction<string[] | undefined>) {
      setLocations(state.filters, action.payload);
    },
    addListLocation(state, action: PayloadAction<string>) {
      addLocationToFilters(state.filters, action.payload);
    },
    removeListLocation(state, action: PayloadAction<string>) {
      removeLocationFromFilters(state.filters, action.payload);
    },
    clearListLocations(state) {
      clearLocationsUtil(state.filters);
    },

    // Department
    addListDepartment(state, action: PayloadAction<string>) {
      addDepartmentToFilters(state.filters, action.payload);
    },
    removeListDepartment(state, action: PayloadAction<string>) {
      removeDepartmentFromFilters(state.filters, action.payload);
    },
    clearListDepartments(state) {
      clearDepartmentsUtil(state.filters);
    },
    setListDepartment(state, action: PayloadAction<string[] | undefined>) {
      setDepartments(state.filters, action.payload);
    },

    // Employment type
    setListEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.filters.employmentType = action.payload;
    },

    // Role category
    addListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      addRoleCategoryToFilters(state.filters, action.payload);
    },
    removeListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      removeRoleCategoryFromFilters(state.filters, action.payload);
    },
    clearListRoleCategories(state) {
      clearRoleCategoriesUtil(state.filters);
    },
    setListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory[] | undefined>) {
      setRoleCategories(state.filters, action.payload);
    },

    // Software only - now manages search tags instead of boolean flag
    toggleListSoftwareOnly(state) {
      toggleSoftwareOnlyInFilters(state.filters);
    },
    setListSoftwareOnly(state, action: PayloadAction<boolean>) {
      setSoftwareOnlyInFilters(state.filters, action.payload);
    },

    // Reset
    resetListFilters(state) {
      state.filters = initialState.filters;
    },

    // Sync from graph (for cross-slice sync)
    syncListFromGraph(state, action: PayloadAction<ListFilters>) {
      state.filters = action.payload;
    },
  },
});

export const {
  setListTimeWindow,
  setListSearchTags,
  addListSearchTag,
  removeListSearchTag,
  toggleListSearchTagMode,
  clearListSearchTags,
  setListLocation,
  addListLocation,
  removeListLocation,
  clearListLocations,
  addListDepartment,
  removeListDepartment,
  clearListDepartments,
  setListDepartment,
  setListEmploymentType,
  addListRoleCategory,
  removeListRoleCategory,
  clearListRoleCategories,
  setListRoleCategory,
  toggleListSoftwareOnly,
  setListSoftwareOnly,
  resetListFilters,
  syncListFromGraph,
} = listFiltersSlice.actions;

export default listFiltersSlice.reducer;
