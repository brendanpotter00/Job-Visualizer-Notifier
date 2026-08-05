import { createSelector } from '@reduxjs/toolkit';
import { selectRecentJobsFilters } from './recentJobsSelectors.ts';
import { selectEnabledCompanyIds } from '../../preferences/enabledCompaniesSlice.ts';
import { selectDemoModeEnabled } from '../../ui/uiSlice.ts';

/** Sorted, order-insensitive rendering of a multi-select filter value. */
function stableList(values: readonly string[] | undefined): string[] {
  return values ? [...values].sort() : [];
}

/**
 * A stable string identity for "which jobs the Recent list is asking for".
 *
 * Exists because the list's incremental-render window has to reset to the first
 * batch when the RESULT SET changes, and `jobs.length` is the wrong proxy for
 * that in both directions:
 *
 * - **False negative.** Two different filters can produce the same count — swap
 *   `location: Seattle` for `location: Austin` and land on 120 rows both times.
 *   Keyed on length, the window never resets, so a user who had scrolled 800
 *   rows deep sees 800 rows of the *new* filter without asking for them.
 * - **False positive.** The list's own data grows underneath it: a scrape tick
 *   lands new rows, or the keyset walk appends a page. Keyed on length, that
 *   yanks the window back to the first batch mid-scroll, discarding everything
 *   the user had scrolled through — for a change they did not make.
 *
 * Keying on this signature resets on exactly the user-driven changes and on
 * nothing else. Two inputs beyond the filter slice are included because they
 * are filters in everything but name — both are applied by
 * `selectAllJobsFromQuery` upstream, so toggling either swaps the result set as
 * decisively as a dropdown does: the enabled-companies set, and the admin demo
 * mode that substitutes the curated `DEMO_JOBS` for live data entirely.
 *
 * Memoized, so the string identity is stable across unrelated store updates and
 * can be used directly as an effect dependency.
 */
export const selectRecentJobsFilterSignature = createSelector(
  [selectRecentJobsFilters, selectEnabledCompanyIds, selectDemoModeEnabled],
  (filters, enabledCompanyIds, demoModeEnabled) =>
    JSON.stringify({
      timeWindow: filters.timeWindow,
      // Tag order is not meaningful to the filter, so sort: re-ordering a
      // keyword list must not look like a new filter.
      searchTags: stableList(
        (filters.searchTags ?? []).map((tag) => `${tag.mode}:${tag.text}`)
      ),
      location: stableList(filters.location),
      employmentType: filters.employmentType ?? null,
      softwareOnly: filters.softwareOnly,
      company: stableList(filters.company),
      category: stableList(filters.category),
      level: stableList(filters.level),
      // null (not loaded / no preference) is distinct from [] and from a set.
      enabledCompanies: enabledCompanyIds ? [...enabledCompanyIds].sort() : null,
      demoMode: demoModeEnabled,
    })
);
