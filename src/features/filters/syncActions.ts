import type { AppDispatch, RootState } from '../../app/store';
import { syncGraphFromList, resetGraphFilters } from './slices/graphFiltersSlice.ts';
import { syncListFromGraph, resetListFilters } from './slices/listFiltersSlice.ts';
import { selectGraphFilters } from './selectors/graphFiltersSelectors.ts';
import { selectListFilters } from './selectors/listFiltersSelectors.ts';

/**
 * Sync graph filters to list filters
 * Reads current graph state and copies it to list
 */
export const syncGraphToList = () => (dispatch: AppDispatch, getState: () => RootState) => {
  const graphFilters = selectGraphFilters(getState());
  dispatch(syncListFromGraph(graphFilters));
};

/**
 * Sync list filters to graph filters
 * Reads current list state and copies it to graph
 */
export const syncListToGraph = () => (dispatch: AppDispatch, getState: () => RootState) => {
  const listFilters = selectListFilters(getState());
  dispatch(syncGraphFromList(listFilters));
};

/**
 * Reset all filters (both graph and list) to their initial state
 */
export const resetAllFilters = () => (dispatch: AppDispatch) => {
  dispatch(resetGraphFilters());
  dispatch(resetListFilters());
};
