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
          searchTags: trendTags,
        })
      );
      dispatch(
        hydrateRecentJobsFilters({
          timeWindow: savedFilters.recentTimeWindow,
          location: savedFilters.locations,
          searchTags: recentTags,
        })
      );
      return;
    }

    // Logged out. Only reset on the actual transition from authenticated so we
    // don't stomp anonymous users' in-session filter tweaks on every render.
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
