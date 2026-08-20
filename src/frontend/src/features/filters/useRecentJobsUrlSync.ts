import { useEffect, useRef } from 'react';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  hydrateRecentJobsFilters,
  setRecentJobsHydrated,
} from './slices/recentJobsFiltersSlice';
import { buildSearchFromFilters, parseFiltersFromSearch } from './urlFilters';

/**
 * Two-way binding between the Recent page's filters and the browser URL.
 *
 * READ (once, on mount): if the URL carries filter params, hydrate the slice
 * from them. Because `hydrateRecentJobsFilters` is one-shot — guarded by the
 * slice's own `hydrated` flag — doing this BEFORE the saved-filters request
 * resolves makes the later `useHydrateSavedFilters` dispatch a no-op. That is
 * the whole implementation of "a shared URL wins for that visit": the reader's
 * saved filters are never read into the page and never written to, so their own
 * set is intact on their next normal visit. No new precedence mechanism, no flag
 * to keep in sync — the guard that already existed does it.
 *
 * The read is synchronous on mount while saved filters need a round trip, so the
 * ordering holds without a race. Mounting this hook BEFORE
 * `useHydrateSavedFilters` at the app root makes that explicit rather than
 * incidental.
 *
 * WRITE: `replaceState`, not `pushState`. The address bar should always match
 * what you are looking at so copying it just works, but a filter tweak is not a
 * navigation — with `pushState`, Back would step backwards through every
 * intermediate filter state (and the 300ms debounce means there are more of
 * those than the reader made) instead of leaving the page. Chosen with the repo
 * owner.
 */
export function useRecentJobsUrlSync(): void {
  const dispatch = useAppDispatch();
  const filters = useAppSelector((state) => state.recentJobsFilters.filters);
  const hydrated = useAppSelector((state) => state.recentJobsFilters.hydrated);

  // Whether this page load arrived with filters in the URL. Read once, before
  // any write can happen, so the write effect below cannot mistake its own
  // output for an incoming shared link.
  const arrivedWithParams = useRef<boolean | null>(null);
  if (arrivedWithParams.current === null) {
    arrivedWithParams.current = parseFiltersFromSearch(window.location.search) !== null;
  }

  // READ — once, as early as possible.
  useEffect(() => {
    const fromUrl = parseFiltersFromSearch(window.location.search);
    if (!fromUrl) return;
    dispatch(hydrateRecentJobsFilters(fromUrl));
    // `hydrate` sets the flag itself, but only on the first call. Setting it
    // explicitly keeps this correct if a shared link ever arrives after some
    // other code path has already hydrated — the URL still wins for this visit.
    dispatch(setRecentJobsHydrated(true));
    // Mount-only on purpose: this reads the URL the reader ARRIVED on. Later URL
    // changes are this hook's own `replaceState` writes, and re-reading them
    // would be a loop. `window.location` is not reactive, so `[dispatch]` is a
    // complete dependency list and no lint suppression is needed here —
    // src/frontend/CLAUDE.md forbids new eslint-disable directives, and this one
    // was both unnecessary and against that rule.
  }, [dispatch]);

  // WRITE — mirror filter state into the address bar.
  useEffect(() => {
    // Wait for hydration. Writing before it would stamp the slice's DEFAULTS
    // over a shared link's params in the window between mount and hydration,
    // destroying the very link the reader followed.
    if (!hydrated) return;

    const next = buildSearchFromFilters(filters, window.location.search);
    const current = window.location.search;
    if (next === current) return;

    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${next}${window.location.hash}`
    );
  }, [filters, hydrated]);
}
