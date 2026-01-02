import { createFilterSlice } from './createFilterSlice';
import type { RecentJobsFilters } from '../../../types';

/**
 * Initial filter state for Recent Jobs page
 * Default time window is 3 hours
 * No department or roleCategory filters
 */
const initialFilters: RecentJobsFilters = {
  timeWindow: '3h',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
  company: undefined,
};

/**
 * Recent Jobs filter slice created via factory pattern
 * Generates 25 action creators automatically
 */
const recentJobsFiltersSlice = createFilterSlice('recentJobs', initialFilters);

/**
 * Export only the actions we want to use
 * (Department and roleCategory actions are generated but not exported)
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
  setRecentJobsTimeWindow,
  setRecentJobsSearchTags,
  addRecentJobsSearchTag,
  removeRecentJobsSearchTag,
  toggleRecentJobsSearchTagMode,
  clearRecentJobsSearchTags,
  setRecentJobsLocation,
  addRecentJobsLocation,
  removeRecentJobsLocation,
  clearRecentJobsLocations,
  setRecentJobsEmploymentType,
  toggleRecentJobsSoftwareOnly,
  setRecentJobsSoftwareOnly,
  toggleRecentJobsRoleGroup,
  setRecentJobsRoleGroup,
  clearRecentJobsRoleGroups,
  setRecentJobsCompany,
  addRecentJobsCompany,
  removeRecentJobsCompany,
  clearRecentJobsCompanies,
  resetRecentJobsFilters,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} = recentJobsFiltersSlice.actions as any;

export default recentJobsFiltersSlice.reducer;
