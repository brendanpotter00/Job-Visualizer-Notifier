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
 * Two jobs, both about change DETECTION rather than about the query itself:
 *
 * 1. It is the debounce key. `useRecentJobsSearch` waits for this string to
 *    settle before issuing a request, so a burst of edits (typing a keyword,
 *    ticking three levels) costs one search instead of one per keystroke.
 * 2. It stamps the recency bound. `since` is frozen for the lifetime of a walk —
 *    the server rejects a cursor whose `since` moved — and this signature is
 *    what says a genuinely new walk has begun and the bound may be re-minted.
 *
 * Two inputs beyond the filter slice are included because they are filters in
 * everything but name: the enabled-companies set, which is folded into the
 * `company` parameter, and the admin demo mode, which substitutes the curated
 * `DEMO_JOBS` for live data entirely. Toggling either swaps the result set as
 * decisively as a dropdown does.
 *
 * Multi-select values are sorted, so reordering a selection is not a change.
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
