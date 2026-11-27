import { useEffect, useRef } from 'react';
import { useAppDispatch } from '../../app/hooks';
import { useAuth } from '../auth/useAuth';
import { useCurrentUser } from '../auth/useCurrentUser';
import { getPostHogSessionId } from '../analytics/events';
import { hydrateRecentJobsFilters } from '../filters/slices/recentJobsFiltersSlice';
import {
  savedFiltersApi,
  useCompleteOnboardingMutation,
  useGetKeywordListsQuery,
  useGetSavedFiltersQuery,
} from '../savedFilters/savedFiltersApi';
import { toOnboardingAnswers, toRecentFiltersPatch } from './defaultSearch';
import { clearPendingDefaultSearch, pendingDefaultSearchAtLoad } from './pendingDefaultSearch';
import { useSaveDefaultSearch } from './useSaveDefaultSearch';

/**
 * Finishes a "Save default search" that a signed-out reader started: the click
 * stored the search (`pendingDefaultSearch`) and sent them to sign in; this runs
 * on the page load they come back to.
 *
 * Mounted in `AppContent` AFTER `useRecentJobsUrlSync` and BEFORE
 * `useHydrateSavedFilters`, and the order is load-bearing:
 *
 * - RESTORE, on the first effect: the search goes into the Recent slice with
 *   `hydrateRecentJobsFilters`. Hydration is one-shot, so the saved-filters
 *   hydration that follows is a no-op for the Recent slice and the page shows
 *   (and searches) the pending filters, never the old saved default.
 * - DISCARD: once auth resolves signed out (the sign-in was cancelled), the
 *   pending search is dropped. Nothing is sent.
 * - APPLY, once: signed in, saved filters and keyword lists loaded, and the
 *   current user loaded or failed. A brand-new account (`onboardingCompletedAt
 *   === null`) is first stamped with the search's answers, because
 *   `OnboardingGate` keeps the first-sign-in questions closed for this load
 *   (`hadPendingDefaultSearchAtLoad`). A failed stamp is ignored (the questions
 *   open on the next load, as after a failed Skip). Then the search is saved
 *   exactly as a signed-in click saves it, and the pending search is cleared.
 *   A reload during the save re-applies the same values, which is safe.
 */
export function useApplyPendingDefaultSearch(): void {
  const dispatch = useAppDispatch();
  const { isAuthenticated, isLoading } = useAuth();
  const { user, setUser, error: userError } = useCurrentUser();
  const { data: savedFilters } = useGetSavedFiltersQuery(undefined, { skip: !isAuthenticated });
  const { data: keywordLists } = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });
  const [completeOnboarding] = useCompleteOnboardingMutation();
  const { save } = useSaveDefaultSearch();
  const restored = useRef(false);
  const started = useRef(false);

  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    const pending = pendingDefaultSearchAtLoad();
    if (pending) dispatch(hydrateRecentJobsFilters(toRecentFiltersPatch(pending)));
  }, [dispatch]);

  useEffect(() => {
    if (started.current || isLoading || isAuthenticated) return;
    if (pendingDefaultSearchAtLoad()) clearPendingDefaultSearch();
  }, [isLoading, isAuthenticated]);

  useEffect(() => {
    if (started.current || !isAuthenticated) return;
    const pending = pendingDefaultSearchAtLoad();
    if (!pending || !savedFilters || !keywordLists) return;
    if (user === null && userError === null) return;
    started.current = true;

    void (async () => {
      let current = savedFilters;
      try {
        if (user?.onboardingCompletedAt === null) {
          try {
            const result = await completeOnboarding({
              ...toOnboardingAnswers(pending),
              skipped: false,
              sessionId: getPostHogSessionId(),
            }).unwrap();
            await dispatch(
              savedFiltersApi.util.upsertQueryData('getSavedFilters', undefined, result.savedFilters)
            );
            setUser((u) => (u ? { ...u, onboardingCompletedAt: result.onboardingCompletedAt } : u));
            current = result.savedFilters;
          } catch (err) {
            console.error('[useApplyPendingDefaultSearch] onboarding stamp failed', err);
          }
        }
        await save(pending, { current, lists: keywordLists });
      } finally {
        clearPendingDefaultSearch();
      }
    })();
  }, [
    isAuthenticated,
    savedFilters,
    keywordLists,
    user,
    userError,
    setUser,
    completeOnboarding,
    save,
    dispatch,
  ]);
}
