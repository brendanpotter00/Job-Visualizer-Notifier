import { describe, it, expect } from 'vitest';
import recentJobsFiltersReducer, {
  hydrateRecentJobsFilters,
  resetRecentJobsFilters,
  setRecentJobsCompanyCategory,
  setRecentJobsLevel,
} from '../../../features/filters/slices/recentJobsFiltersSlice';
import graphFiltersReducer from '../../../features/filters/slices/graphFiltersSlice';
import * as graphActions from '../../../features/filters/slices/graphFiltersSlice';
import { createFilterSlice } from '../../../features/filters/slices/createFilterSlice';

/**
 * The Recent page's company type lives on the Recent slice only. It is added
 * through `createFilterSlice`'s slice-only reducers, so these tests pin that
 * it behaves like the generated facet setters.
 */
describe('setRecentJobsCompanyCategory', () => {
  const initial = () => recentJobsFiltersReducer(undefined, { type: '@@init' });

  it('sets the selection', () => {
    const state = recentJobsFiltersReducer(initial(), setRecentJobsCompanyCategory(['big_tech']));
    expect(state.filters.companyCategory).toEqual(['big_tech']);
  });

  it('normalizes [] and undefined to undefined (the All state)', () => {
    let state = recentJobsFiltersReducer(initial(), setRecentJobsCompanyCategory(['big_tech']));
    state = recentJobsFiltersReducer(state, setRecentJobsCompanyCategory([]));
    expect(state.filters.companyCategory).toBeUndefined();
    state = recentJobsFiltersReducer(state, setRecentJobsCompanyCategory(['fintech']));
    state = recentJobsFiltersReducer(state, setRecentJobsCompanyCategory(undefined));
    expect(state.filters.companyCategory).toBeUndefined();
  });

  it('is an edit: it flips userModified, so a late hydration keeps it', () => {
    let state = recentJobsFiltersReducer(initial(), setRecentJobsCompanyCategory(['ai_labs']));
    expect(state.userModified).toBe(true);
    state = recentJobsFiltersReducer(
      state,
      hydrateRecentJobsFilters({ companyCategory: ['fintech'] })
    );
    expect(state.filters.companyCategory).toEqual(['ai_labs']);
    expect(state.hydrated).toBe(true);
  });

  it('is cleared by Reset (the key is in initialFilters)', () => {
    let state = recentJobsFiltersReducer(initial(), setRecentJobsCompanyCategory(['big_tech']));
    state = recentJobsFiltersReducer(state, setRecentJobsLevel(['senior']));
    state = recentJobsFiltersReducer(state, resetRecentJobsFilters());
    expect(state.filters.companyCategory).toBeUndefined();
    expect(state.filters.level).toBeUndefined();
    expect(state.userModified).toBe(false);
    expect('companyCategory' in state.filters).toBe(true);
  });

  it('does not exist on the graph slice', () => {
    expect('setGraphCompanyCategory' in graphActions).toBe(false);
    const state = graphFiltersReducer(undefined, { type: '@@init' });
    expect('companyCategory' in state.filters).toBe(false);
  });
});

describe('createFilterSlice slice-only reducers', () => {
  it('are merged beside the generated ones and covered by the userModified matcher', () => {
    const slice = createFilterSlice(
      'recentJobs',
      { timeWindow: 'all', softwareOnly: false },
      {
        setRecentJobsThing: (state, action) => {
          state.filters.category = action.payload;
        },
      }
    );
    expect(slice.actions).toHaveProperty('setRecentJobsThing');
    expect(slice.actions).toHaveProperty('setRecentJobsLevel');
    const state = slice.reducer(slice.getInitialState(), {
      type: 'recentJobsFilters/setRecentJobsThing',
      payload: ['x'],
    });
    expect(state.filters.category).toEqual(['x']);
    expect(state.userModified).toBe(true);
  });
});
