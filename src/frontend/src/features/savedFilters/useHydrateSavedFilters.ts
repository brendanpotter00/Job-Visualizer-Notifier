import { useEffect, useRef } from 'react';
import { useAuth } from '../auth/useAuth';
import { useAppDispatch } from '../../app/hooks';
import {
  hydrateGraphFilters,
  resetGraphFilters,
  setGraphHydrated,
} from '../filters/slices/graphFiltersSlice';
import {
  hydrateRecentJobsFilters,
  resetRecentJobsFilters,
  setRecentJobsHydrated,
} from '../filters/slices/recentJobsFiltersSlice';
import {
  useGetSavedFiltersQuery,
  useGetKeywordListsQuery,
  savedFiltersApi,
} from './savedFiltersApi';
import { resolveActiveTags } from './resolveActiveTags';

/**
 * Loads the signed-in user's saved filters once and hydrates the graph and
 * recent-jobs filter slices from them. Mirrors `useEnabledCompanies`: mount once
 * at the app root so the slices are seeded before any page reads them.
 *
 * Hydration is one-shot per slice (guarded by the slices' `hydrated` flag), so a
 * re-render or a late-arriving query result never clobbers edits the user has
 * since made. On logout the slices are reset, their `hydrated` flag cleared, and
 * the saved-filters API cache is reset, so the next sign-in re-hydrates from fresh
 * saved filters for the current user (never the previous user's cached data).
 */
export function useHydrateSavedFilters(): void {
  const { isAuthenticated } = useAuth();
  const dispatch = useAppDispatch();

  const { data: savedFilters } = useGetSavedFiltersQuery(undefined, { skip: !isAuthenticated });
  const { data: keywordLists } = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  // Remember whether we were authenticated last render so we can detect the
  // logged-in -> logged-out transition and reset exactly once.
  const wasAuthenticated = useRef(false);

  useEffect(() => {
    if (isAuthenticated) {
      wasAuthenticated.current = true;

      // Both requests must have resolved before we hydrate: the active-list ids
      // in `savedFilters` are resolved against `keywordLists`.
      if (!savedFilters || !keywordLists) return;

      const trendTags = resolveActiveTags(savedFilters.trendActiveKeywordListId, keywordLists);
      const recentTags = resolveActiveTags(savedFilters.recentActiveKeywordListId, keywordLists);

      dispatch(
        hydrateGraphFilters({
          timeWindow: savedFilters.trendTimeWindow,
          location: savedFilters.locations,
          category: savedFilters.category,
          level: savedFilters.level,
          // Safe by construction on a LEGACY row: the payload is a Partial<T>
          // applied via Object.assign, and `validateSavedFilters` guarantees
          // this key is at least `[]`. `[]` hydrates as an empty array rather
          // than undefined, which every consumer already treats as "no filter"
          // (matchesSubcategory checks .length, stableList maps both to [], and
          // the slice reducer normalizes [] back to undefined on the next edit).
          subcategory: savedFilters.subcategory,
          searchTags: trendTags,
        })
      );
      dispatch(
        hydrateRecentJobsFilters({
          timeWindow: savedFilters.recentTimeWindow,
          location: savedFilters.locations,
          category: savedFilters.category,
          level: savedFilters.level,
          subcategory: savedFilters.subcategory,
          searchTags: recentTags,
        })
      );
      return;
    }

    // Logged out. Only reset on the actual transition from authenticated so we
    // don't stomp anonymous users' in-session filter tweaks on every render.
    //
    // THE ADDRESS BAR IS CLEARED BY THE RESET BELOW, not here, and that is a
    // dependency worth knowing about. `resetRecentJobsFilters` changes
    // `filters`, which re-runs `useRecentJobsUrlSync`'s write effect, which
    // rebuilds the query string from the (now default) filter set and drops
    // every param it owns. That matters most on the path with no page load at
    // all — a silent Auth0 session expiry or a failed refresh — where the ex
    // user's `?time=…&tag=…` would otherwise sit in the bar above a defaults
    // page and be re-applied verbatim by the next reload. (The Logout BUTTON
    // redirects through `auth0Logout` and takes the URL with it, so it never
    // showed the problem.) The write effect's gate must therefore stay
    // independent of `hydrated` — `setRecentJobsHydrated(false)` two lines down
    // used to silence it, which is what left the params behind.
    if (wasAuthenticated.current) {
      wasAuthenticated.current = false;
      dispatch(resetGraphFilters());
      dispatch(resetRecentJobsFilters());
      dispatch(setGraphHydrated(false));
      dispatch(setRecentJobsHydrated(false));
      // Clear the cached saved-filters/keyword-lists so a subsequent login - e.g. a
      // different user via Google One Tap, which does not reload the page - cannot
      // hydrate filters from the previous user's still-cached data.
      dispatch(savedFiltersApi.util.resetApiState());
    }
  }, [isAuthenticated, savedFilters, keywordLists, dispatch]);
}
