import { createFilterSlice } from './createFilterSlice';
import type { RecentJobsFilters } from '../../types';

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
  setRecentJobsCompany,
  addRecentJobsCompany,
  removeRecentJobsCompany,
  clearRecentJobsCompanies,
  resetRecentJobsFilters,
} = recentJobsFiltersSlice.actions as any;

export default recentJobsFiltersSlice.reducer;
