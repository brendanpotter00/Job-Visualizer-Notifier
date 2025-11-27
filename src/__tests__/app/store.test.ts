import { describe, it, expect } from 'vitest';
import { store } from '../../app/store';

describe('Redux Store', () => {
  it('should initialize with expected shape', () => {
    const state = store.getState();

    expect(state).toHaveProperty('app');
    expect(state).toHaveProperty('jobs');
    expect(state).toHaveProperty('graphFilters');
    expect(state).toHaveProperty('listFilters');
    expect(state).toHaveProperty('ui');
  });

  it('should have correct initial app state', () => {
    const state = store.getState();

    expect(state.app.selectedCompanyId).toBe('spacex');
    expect(state.app.selectedView).toBe('greenhouse');
    expect(state.app.isInitialized).toBe(false);
  });

  it('should have correct initial jobs state', () => {
    const state = store.getState();

    expect(state.jobs.byCompany).toEqual({});
  });

  it('should have correct initial filters state', () => {
    const state = store.getState();

    expect(state.graphFilters.filters.timeWindow).toBe('30d');
    expect(state.graphFilters.filters.softwareOnly).toBe(false);
    expect(state.listFilters.filters.timeWindow).toBe('24h');
    expect(state.listFilters.filters.searchTags).toBeUndefined();
  });

  it('should have correct initial UI state', () => {
    const state = store.getState();

    expect(state.ui.graphModal.open).toBe(false);
    expect(state.ui.globalLoading).toBe(false);
    expect(state.ui.notifications).toEqual([]);
  });
});
