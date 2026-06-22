import type { GraphFilters } from '../../../types';
import { createFilterSlice, type FiltersState } from './createFilterSlice';

/**
 * Graph filter state. Aliased to the factory's `FiltersState<GraphFilters>` so
 * it stays the single source of truth (and carries the `hydrated` flag).
 */
export type GraphFiltersState = FiltersState<GraphFilters>;

const initialFilters: GraphFilters = {
  timeWindow: '7d',
  searchTags: undefined,
  location: undefined,
  department: undefined,
  employmentType: undefined,
  softwareOnly: false,
};

const graphFiltersSlice = createFilterSlice('graph', initialFilters);

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
  toggleGraphSoftwareOnly,
  setGraphSoftwareOnly,
  hydrateGraphFilters,
  setGraphHydrated,
  resetGraphFilters,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} = graphFiltersSlice.actions as any;

export default graphFiltersSlice.reducer;
