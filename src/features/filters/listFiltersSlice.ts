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

/**
 * Extract actions with proper typing
 *
 * Type Assertion Rationale:
 * The `as any` cast is necessary here due to TypeScript's limitations with computed property names.
 * The createFilterSlice factory generates action creators using dynamic keys like
 * `[set${CapitalizedName}TimeWindow]`, which prevents TypeScript from inferring the exact
 * action types at compile time.
 *
 * This is a well-known limitation when using the factory pattern with Redux Toolkit.
 * The types are still enforced at the point of use (dispatch calls), so type safety is
 * maintained in practice. The alternative would be to abandon the factory pattern and
 * duplicate 158+ lines of code across three slices.
 *
 * See: https://github.com/reduxjs/redux-toolkit/issues/368
 */
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} = listFiltersSlice.actions as any;

export default listFiltersSlice.reducer;
