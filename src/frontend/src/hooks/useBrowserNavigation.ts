import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../app/hooks';
import { setSelectedCompanyId } from '../features/app/appSlice';
import { getCompanyFromURL } from '../lib/url';
import { ROUTES } from '../config/routes';
import { selectUserCompanyIdSet } from '../features/userCompanies/effectiveCompanies';

/**
 * Custom hook for handling browser back/forward navigation
 *
 * Responsibilities:
 * - Listen to popstate events (browser back/forward) - Companies page only
 * - Sync Redux state with URL changes
 * - Clean up event listener on unmount
 *
 * This hook enables users to navigate between companies using browser
 * back/forward buttons while keeping the app state synchronized.
 *
 * Note: This hook only runs on the Companies page to prevent conflicts
 * with React Router's navigation.
 */
export function useBrowserNavigation() {
  const location = useLocation();
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  // Back/forward onto a `?company=u-…` entry is only reachable once the user has
  // already selected that board, so the set is populated by then — no gate is
  // needed here, unlike the cold load in `useCompanyLoader`. Empty by identity
  // for a signed-out or flag-off visitor, so this is a no-op for them.
  const userCompanyIds = useAppSelector(selectUserCompanyIdSet);

  // Only run on Companies page
  const isCompaniesPage = location.pathname === ROUTES.COMPANIES;

  useEffect(() => {
    if (!isCompaniesPage) return;

    const handlePopState = () => {
      const companyFromURL = getCompanyFromURL(userCompanyIds);
      if (companyFromURL && companyFromURL !== selectedCompanyId) {
        dispatch(setSelectedCompanyId(companyFromURL));
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [dispatch, selectedCompanyId, isCompaniesPage, userCompanyIds]);
}
