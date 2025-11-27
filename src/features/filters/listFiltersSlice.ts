import type { ListFilters } from '../../types';
import { createFilterSlice } from './createFilterSlice';

/**
 * List filter state
 */
export interface ListFiltersState {
  filters: ListFilters;
}

const initialFilters: ListFilters = {
  timeWindow: '24h',
  searchTags: undefined,
  softwareOnly: false,
  roleCategory: undefined,
};

const listFiltersSlice = createFilterSlice('list', initialFilters);

// Extract actions with proper typing
// TypeScript can't infer action types from computed property names, so we cast here
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
} = listFiltersSlice.actions as any;

export default listFiltersSlice.reducer;
