import { useDispatch, useSelector } from 'react-redux';
import type { TypedUseSelectorHook } from 'react-redux';
import type { RootState, AppDispatch } from './store';
import { useEffect, useRef } from 'react';
import { updateURLWithCompany } from '../utils/urlParams';

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
 * Updates the URL whenever the selected company changes in Redux state
 */
export function useURLSync(): void {
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const isInitialMount = useRef(true);

  useEffect(() => {
    // Skip URL update on initial mount to avoid creating unnecessary history entry
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    // Update URL with current company
    updateURLWithCompany(selectedCompanyId);
  }, [selectedCompanyId]);
}

// Re-export custom hooks for convenience
export { useCompanyLoader } from './hooks/useCompanyLoader';
export { useBrowserNavigation } from './hooks/useBrowserNavigation';
