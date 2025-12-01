import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../hooks';
import { setSelectedCompanyId } from '../../features/app/appSlice';
import { getCompanyFromURL } from '../../utils/urlParams';
import { ROUTES } from '../../config/routes';

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

  // Only run on Companies page
  const isCompaniesPage = location.pathname === ROUTES.COMPANIES;

  useEffect(() => {
    if (!isCompaniesPage) return;

    const handlePopState = () => {
      const companyFromURL = getCompanyFromURL();
      if (companyFromURL && companyFromURL !== selectedCompanyId) {
        dispatch(setSelectedCompanyId(companyFromURL));
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [dispatch, selectedCompanyId, isCompaniesPage]);
}
