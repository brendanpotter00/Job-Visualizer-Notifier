import { useEffect } from 'react';
import { useAppDispatch, useAppSelector } from '../hooks';
import { selectCompany } from '../../features/app/appSlice';
import { getCompanyFromURL } from '../../utils/urlParams';

/**
 * Custom hook for handling browser back/forward navigation
 *
 * Responsibilities:
 * - Listen to popstate events (browser back/forward)
 * - Sync Redux state with URL changes
 * - Clean up event listener on unmount
 *
 * This hook enables users to navigate between companies using browser
 * back/forward buttons while keeping the app state synchronized.
 */
export function useBrowserNavigation() {
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);

  useEffect(() => {
    const handlePopState = () => {
      const companyFromURL = getCompanyFromURL();
      if (companyFromURL && companyFromURL !== selectedCompanyId) {
        dispatch(selectCompany(companyFromURL));
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [dispatch, selectedCompanyId]);
}
