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
import { SOFTWARE_ENGINEERING_TAGS } from '../../constants/tags';
import { useGetPreferencesQuery, useGetKeywordListsQuery } from './preferencesApi';
import type { KeywordList, SearchTag } from '../../types';

/** Backend id for the synthesized, read-only "Software Engineering" list. */
const BUILTIN_SWE_ID = 'builtin-swe';

/**
 * Resolve a saved active-list id to the concrete `searchTags` to hydrate.
 * - `null` (no keyword filter) -> `undefined`
 * - built-in SWE id -> a fresh copy of `SOFTWARE_ENGINEERING_TAGS`
 * - any other id -> the matching list's tags (or `undefined` if it no longer exists)
 */
function resolveActiveTags(
  activeId: string | null,
  lists: KeywordList[]
): SearchTag[] | undefined {
  if (activeId === null) return undefined;
  if (activeId === BUILTIN_SWE_ID) {
    return SOFTWARE_ENGINEERING_TAGS.map((tag) => ({ ...tag }));
  }
  const match = lists.find((l) => l.id === activeId);
  return match ? match.tags.map((tag) => ({ ...tag })) : undefined;
}

/**
 * Loads the signed-in user's saved preferences once and hydrates the graph and
 * recent-jobs filter slices from them. Mirrors `useEnabledCompanies`: mount once
 * at the app root so the slices are seeded before any page reads them.
 *
 * Hydration is one-shot per slice (guarded by the slices' `hydrated` flag), so a
 * re-render or a late-arriving query result never clobbers edits the user has
 * since made. On logout the slices are reset and their `hydrated` flag cleared so
 * the next sign-in re-hydrates from fresh preferences.
 */
export function useHydrateFilterPreferences(): void {
  const { isAuthenticated } = useAuth();
  const dispatch = useAppDispatch();

  const { data: preferences } = useGetPreferencesQuery(undefined, { skip: !isAuthenticated });
  const { data: keywordLists } = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  // Remember whether we were authenticated last render so we can detect the
  // logged-in -> logged-out transition and reset exactly once.
  const wasAuthenticated = useRef(false);

  useEffect(() => {
    if (isAuthenticated) {
      wasAuthenticated.current = true;

      // Both requests must have resolved before we hydrate: the active-list ids
      // in `preferences` are resolved against `keywordLists`.
      if (!preferences || !keywordLists) return;

      const trendTags = resolveActiveTags(preferences.trendActiveKeywordListId, keywordLists);
      const recentTags = resolveActiveTags(preferences.recentActiveKeywordListId, keywordLists);

      dispatch(
        hydrateGraphFilters({
          timeWindow: preferences.trendTimeWindow,
          location: preferences.locations,
          searchTags: trendTags,
        })
      );
      dispatch(
        hydrateRecentJobsFilters({
          timeWindow: preferences.recentTimeWindow,
          location: preferences.locations,
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
    }
  }, [isAuthenticated, preferences, keywordLists, dispatch]);
}
