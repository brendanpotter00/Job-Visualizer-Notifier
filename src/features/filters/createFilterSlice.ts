import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type {
  GraphFilters,
  ListFilters,
  TimeWindow,
  SoftwareRoleCategory,
  SearchTag,
} from '../../types';
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
 * Type for filter slice name
 */
export type FilterSliceName = 'graph' | 'list';

/**
 * Union type for all filter types
 */
export type Filters = GraphFilters | ListFilters;

/**
 * Filter state structure
 */
export interface FiltersState<T extends Filters> {
  filters: T;
}

/**
 * Capitalize first letter of string
 */
function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Factory function to create filter slices with identical logic.
 *
 * This eliminates 95%+ code duplication between graphFiltersSlice and
 * listFiltersSlice by generating all 25 action creators dynamically.
 *
 * @example
 * ```typescript
 * const graphFiltersSlice = createFilterSlice('graph', {
 *   timeWindow: '30d',
 *   searchTags: undefined,
 *   softwareOnly: false,
 *   roleCategory: undefined,
 * });
 * ```
 *
 * @param name - 'graph' or 'list'
 * @param initialFilters - Initial filter values
 * @returns Redux Toolkit slice with all filter actions
 */
export function createFilterSlice<T extends Filters>(name: FilterSliceName, initialFilters: T) {
  const capitalizedName = capitalize(name);

  const initialState: FiltersState<T> = {
    filters: initialFilters,
  };

  const slice = createSlice({
    name: `${name}Filters`,
    initialState,
    reducers: {
      // Time window
      [`set${capitalizedName}TimeWindow`]: (state, action: PayloadAction<TimeWindow>) => {
        state.filters.timeWindow = action.payload;
      },

      // Search tags (5 actions)
      [`set${capitalizedName}SearchTags`]: (
        state,
        action: PayloadAction<SearchTag[] | undefined>
      ) => {
        setSearchTagsUtil(state.filters, action.payload);
      },
      [`add${capitalizedName}SearchTag`]: (state, action: PayloadAction<SearchTag>) => {
        addSearchTagToFilters(state.filters, action.payload);
      },
      [`remove${capitalizedName}SearchTag`]: (state, action: PayloadAction<string>) => {
        removeSearchTagFromFilters(state.filters, action.payload);
      },
      [`toggle${capitalizedName}SearchTagMode`]: (state, action: PayloadAction<string>) => {
        toggleSearchTagModeUtil(state.filters, action.payload);
      },
      [`clear${capitalizedName}SearchTags`]: (state) => {
        clearSearchTagsUtil(state.filters);
      },

      // Location (4 actions)
      [`set${capitalizedName}Location`]: (state, action: PayloadAction<string[] | undefined>) => {
        setLocations(state.filters, action.payload);
      },
      [`add${capitalizedName}Location`]: (state, action: PayloadAction<string>) => {
        addLocationToFilters(state.filters, action.payload);
      },
      [`remove${capitalizedName}Location`]: (state, action: PayloadAction<string>) => {
        removeLocationFromFilters(state.filters, action.payload);
      },
      [`clear${capitalizedName}Locations`]: (state) => {
        clearLocationsUtil(state.filters);
      },

      // Department (4 actions)
      [`add${capitalizedName}Department`]: (state, action: PayloadAction<string>) => {
        addDepartmentToFilters(state.filters, action.payload);
      },
      [`remove${capitalizedName}Department`]: (state, action: PayloadAction<string>) => {
        removeDepartmentFromFilters(state.filters, action.payload);
      },
      [`clear${capitalizedName}Departments`]: (state) => {
        clearDepartmentsUtil(state.filters);
      },
      [`set${capitalizedName}Department`]: (state, action: PayloadAction<string[] | undefined>) => {
        setDepartments(state.filters, action.payload);
      },

      // Employment type (1 action)
      [`set${capitalizedName}EmploymentType`]: (
        state,
        action: PayloadAction<string | undefined>
      ) => {
        state.filters.employmentType = action.payload;
      },

      // Role category (4 actions)
      [`add${capitalizedName}RoleCategory`]: (
        state,
        action: PayloadAction<SoftwareRoleCategory>
      ) => {
        addRoleCategoryToFilters(state.filters, action.payload);
      },
      [`remove${capitalizedName}RoleCategory`]: (
        state,
        action: PayloadAction<SoftwareRoleCategory>
      ) => {
        removeRoleCategoryFromFilters(state.filters, action.payload);
      },
      [`clear${capitalizedName}RoleCategories`]: (state) => {
        clearRoleCategoriesUtil(state.filters);
      },
      [`set${capitalizedName}RoleCategory`]: (
        state,
        action: PayloadAction<SoftwareRoleCategory[] | undefined>
      ) => {
        setRoleCategories(state.filters, action.payload);
      },

      // Software only (2 actions) - manages search tags instead of boolean flag
      [`toggle${capitalizedName}SoftwareOnly`]: (state) => {
        toggleSoftwareOnlyInFilters(state.filters);
      },
      [`set${capitalizedName}SoftwareOnly`]: (state, action: PayloadAction<boolean>) => {
        setSoftwareOnlyInFilters(state.filters, action.payload);
      },

      // Reset (1 action)
      [`reset${capitalizedName}Filters`]: (state) => {
        // Use Object.assign to work with Immer's Draft type
        Object.assign(state.filters, initialState.filters);
      },

      // Sync (1 action) - for cross-slice synchronization
      [`sync${capitalizedName}From${capitalize(name === 'graph' ? 'list' : 'graph')}`]: (
        state,
        action: PayloadAction<T>
      ) => {
        // Use Object.assign to work with Immer's Draft type
        Object.assign(state.filters, action.payload);
      },
    },
  });

  // Return the slice - TypeScript will infer action types from the actual implementation
  return slice;
}
