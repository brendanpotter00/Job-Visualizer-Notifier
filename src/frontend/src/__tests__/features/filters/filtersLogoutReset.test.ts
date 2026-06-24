import { describe, it, expect } from 'vitest';
import graphReducer, {
  hydrateGraphFilters,
  setGraphHydrated,
  resetGraphFilters,
} from '../../../features/filters/slices/graphFiltersSlice';
import recentJobsReducer, {
  hydrateRecentJobsFilters,
  setRecentJobsHydrated,
  resetRecentJobsFilters,
} from '../../../features/filters/slices/recentJobsFiltersSlice';

/**
 * Regression coverage for the logged-in -> logged-out reset path
 * (see useHydrateSavedFilters): every field that hydration can populate must
 * be cleared by reset. `resetFilters` uses Object.assign(state, initialFilters),
 * which never deletes keys absent from initialFilters, so any hydrated field
 * missing from initialFilters would leak into the anonymous session.
 */
describe('saved-filters hydrate -> logout reset', () => {
  it('clears every hydrated graph field on reset', () => {
    const initial = graphReducer(undefined, { type: '@@INIT' });

    let state = graphReducer(
      initial,
      hydrateGraphFilters({
        timeWindow: '30d',
        location: ['New York, NY'],
        searchTags: [{ text: 'react', mode: 'include' }],
      })
    );
    // sanity: hydration applied
    expect(state.filters.location).toEqual(['New York, NY']);

    state = graphReducer(state, setGraphHydrated(false));
    state = graphReducer(state, resetGraphFilters());

    expect(state.filters).toEqual(initial.filters);
    expect(state.filters.location).toBeUndefined();
    expect(state.filters.searchTags).toBeUndefined();
    expect(state.filters.timeWindow).toBe('14d');
  });

  it('clears every hydrated recent-jobs field on reset', () => {
    const initial = recentJobsReducer(undefined, { type: '@@INIT' });

    let state = recentJobsReducer(
      initial,
      hydrateRecentJobsFilters({
        timeWindow: '7d',
        location: ['New York, NY'],
        searchTags: [{ text: 'react', mode: 'include' }],
      })
    );
    expect(state.filters.location).toEqual(['New York, NY']);

    state = recentJobsReducer(state, setRecentJobsHydrated(false));
    state = recentJobsReducer(state, resetRecentJobsFilters());

    expect(state.filters).toEqual(initial.filters);
    expect(state.filters.location).toBeUndefined();
    expect(state.filters.searchTags).toBeUndefined();
    expect(state.filters.timeWindow).toBe('14d');
  });
});
