import type { PayloadAction } from '@reduxjs/toolkit';
import { createFilterSlice } from './createFilterSlice';
import type { RecentJobsFilters } from '../../../types';

/**
 * Initial filter state for Recent Jobs page
 * Default time window is all time
 */
const initialFilters: RecentJobsFilters = {
  // Default window for anyone WITHOUT a saved filter (logged-out visitors, and
  // the frame before a signed-in user's saved filters hydrate). Kept in sync
  // with the backend no-saved-row default
  // (`saved_filters_service._DEFAULT_RECENT_TIME_WINDOW`) so every "no saved
  // filter" cohort lands on the same all-time view. The Graph slice keeps its
  // own 90-day default — a trend chart wants a bounded span, a recency feed
  // does not.
  timeWindow: 'all',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
  category: undefined,
  level: undefined,
  // NOT COSMETICS. `reset${Name}Filters` is
  // `Object.assign(state.filters, initialState.filters)`, which copies only the
  // keys PRESENT on the source object. Add `subcategory` to the interface but
  // omit it here and "Reset Filters" silently leaves a subcategory selection
  // active while visibly clearing everything else — and it typechecks, and every
  // existing test passes.
  subcategory: undefined,
  // NOT COSMETICS either, for the same reason: without this key Reset leaves a
  // company type selected.
  companyCategory: undefined,
};

/**
 * Recent Jobs filter slice created via factory pattern.
 * Generates 19 action creators automatically, plus the Recent-only
 * `setRecentJobsCompanyCategory` (the trend page is one company, so the graph
 * slice has no company type).
 */
const recentJobsFiltersSlice = createFilterSlice('recentJobs', initialFilters, {
  // `[]` normalizes to `undefined` (the "All" state), like the facet setters.
  setRecentJobsCompanyCategory: (state, action: PayloadAction<string[] | undefined>) => {
    state.filters.companyCategory = action.payload?.length ? action.payload : undefined;
  },
});

/**
 * Export the generated actions.
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
  setRecentJobsCategory,
  setRecentJobsLevel,
  setRecentJobsSubcategory,
  setRecentJobsCompanyCategory,
  toggleRecentJobsSoftwareOnly,
  setRecentJobsSoftwareOnly,
  hydrateRecentJobsFilters,
  setRecentJobsHydrated,
  resetRecentJobsFilters,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} = recentJobsFiltersSlice.actions as any;

export default recentJobsFiltersSlice.reducer;
