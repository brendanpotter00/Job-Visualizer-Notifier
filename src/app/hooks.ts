import { useDispatch, useSelector } from 'react-redux';
import type { TypedUseSelectorHook } from 'react-redux';
import type { RootState, AppDispatch } from './store';
import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { updateURLWithCompany } from '../utils/urlParams';
import { ROUTES } from '../config/routes';

/**
 * Typed useDispatch hook
 */
export const useAppDispatch: () => AppDispatch = useDispatch;

/**
 * Typed useSelector hook
 */
export const useAppSelector: TypedUseSelectorHook<RootState> = useSelector;

/**
 * Custom hook to synchronize selected company to URL
 *
 * Updates the URL whenever the selected company changes in Redux state.
 * Only runs on the Companies page to prevent company query params
 * from appearing on other pages.
 */
export function useURLSync(): void {
  const location = useLocation();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const isInitialMount = useRef(true);

  // Only run on Companies page
  const isCompaniesPage = location.pathname === ROUTES.COMPANIES;

  useEffect(() => {
    if (!isCompaniesPage) return;

    // Skip URL update on initial mount to avoid creating unnecessary history entry
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    // Update URL with current company
    updateURLWithCompany(selectedCompanyId);
  }, [selectedCompanyId, isCompaniesPage]);
}

// Re-export custom hooks for convenience
export { useCompanyLoader } from './hooks/useCompanyLoader';
export { useBrowserNavigation } from './hooks/useBrowserNavigation';
