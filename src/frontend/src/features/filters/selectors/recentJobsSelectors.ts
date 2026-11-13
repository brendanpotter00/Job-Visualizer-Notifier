import type { RootState } from '../../../app/store.ts';

export const selectRecentJobsFilters = (state: RootState) => state.recentJobsFilters.filters;

/**
 * Whether saved-filters hydration has RUN for this slice (see
 * `createFilterSlice`'s `hydrate{Name}Filters`).
 *
 * True the instant the hydrated values are written — the flag and the values land
 * in the same store update — which is what makes it usable as a gate: there is no
 * render in which this reads true while `filters` still holds the pre-hydration
 * defaults. It is also set (with nothing seeded) when the slice was already
 * user-modified, because that too is a settled answer to "may I search now".
 */
export const selectRecentJobsFiltersHydrated = (state: RootState) =>
  state.recentJobsFilters.hydrated;
