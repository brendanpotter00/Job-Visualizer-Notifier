import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store.ts';
import { COMPANIES } from '../../../config/companies.ts';
import { selectEnabledCompanyIds } from '../../preferences/enabledCompaniesSlice.ts';
import { selectDemoModeEnabled } from '../../ui/uiSlice.ts';
import { DEMO_JOBS } from '../../jobs/demoJobs.ts';

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

/**
 * Options for the Recent page's company dropdown.
 *
 * Sourced from the static company config intersected with the user's enabled set
 * — NOT from the jobs on screen, which is how this worked while the page held an
 * unfiltered corpus to derive them from. It no longer does: the rows in the cache
 * are the ones matching every active filter, so deriving options from them would
 * make the dropdown list only companies that already pass the OTHER filters, and
 * it would shrink as the reader narrowed the search.
 *
 * The trade-off is deliberate: the dropdown lists every company the reader
 * follows, including ones with no matches under the current filters. That is a
 * stable, predictable list and costs no extra request. The alternative — asking
 * the server for company facet counts on every filter change — is a second query
 * per keystroke for a cosmetic gain.
 *
 * Demo mode narrows to the companies present in the curated fixture, so the
 * dropdown does not offer options that provably match nothing.
 */
export const selectRecentCompanyOptions = createSelector(
  [selectEnabledCompanyIds, selectDemoModeEnabled],
  (enabledIds, demoModeEnabled) => {
    if (demoModeEnabled) {
      const demoIds = new Set(DEMO_JOBS.map((job) => job.company));
      return COMPANIES.filter((company) => demoIds.has(company.id))
        .map((company) => ({ id: company.id, name: company.name }))
        .sort((a, b) => a.name.localeCompare(b.name));
    }
    // null / [] both mean "all companies" — the same semantics the rest of the
    // preferences code uses.
    const enabled = enabledIds && enabledIds.length > 0 ? new Set(enabledIds) : null;
    return COMPANIES.filter((company) => !enabled || enabled.has(company.id))
      .map((company) => ({ id: company.id, name: company.name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }
);
