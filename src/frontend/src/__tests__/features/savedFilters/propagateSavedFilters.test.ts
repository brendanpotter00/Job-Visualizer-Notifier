import { describe, it, expect } from 'vitest';
import graphReducer from '../../../features/filters/slices/graphFiltersSlice';
import recentJobsReducer from '../../../features/filters/slices/recentJobsFiltersSlice';
import { savedFiltersPropagationActions } from '../../../features/savedFilters/propagateSavedFilters';
import type { SavedFilters, KeywordList } from '../../../types';

const lists: KeywordList[] = [
  {
    id: 'builtin-swe',
    name: 'Software Engineering',
    isBuiltin: true,
    position: 999,
    tags: [{ text: 'engineer', mode: 'include' }],
  },
  {
    id: 'list-1',
    name: 'Backend',
    isBuiltin: false,
    position: 0,
    tags: [{ text: 'golang', mode: 'include' }],
  },
];

/** Apply every propagation action to both reducers (each ignores the other's). */
function applyPropagation(saved: SavedFilters, kwLists: KeywordList[]) {
  const actions = savedFiltersPropagationActions(saved, kwLists);
  let graph = graphReducer(undefined, { type: '@@INIT' });
  let recent = recentJobsReducer(undefined, { type: '@@INIT' });
  for (const action of actions) {
    graph = graphReducer(graph, action);
    recent = recentJobsReducer(recent, action);
  }
  return { graph, recent };
}

describe('savedFiltersPropagationActions (Critique #2: no-refresh propagation)', () => {
  it('snaps both slices to the saved time windows, locations, and active lists', () => {
    const saved: SavedFilters = {
      recentTimeWindow: '24h',
      trendTimeWindow: '30d',
      locations: ['San Francisco, CA, US'],
      recentActiveKeywordListId: 'list-1',
      trendActiveKeywordListId: 'builtin-swe',
    };

    const { graph, recent } = applyPropagation(saved, lists);

    // Company (graph) page reads the *trend* defaults.
    expect(graph.filters.timeWindow).toBe('30d');
    expect(graph.filters.location).toEqual(['San Francisco, CA, US']);
    expect(graph.filters.searchTags).toEqual([{ text: 'engineer', mode: 'include' }]);

    // Recent Jobs page reads the *recent* defaults.
    expect(recent.filters.timeWindow).toBe('24h');
    expect(recent.filters.location).toEqual(['San Francisco, CA, US']);
    expect(recent.filters.searchTags).toEqual([{ text: 'golang', mode: 'include' }]);
  });

  it('clears search tags when the active list is null and treats [] as no location filter', () => {
    const saved: SavedFilters = {
      recentTimeWindow: '7d',
      trendTimeWindow: '7d',
      locations: [],
      recentActiveKeywordListId: null,
      trendActiveKeywordListId: null,
    };

    const { graph, recent } = applyPropagation(saved, lists);

    expect(graph.filters.searchTags).toBeUndefined();
    expect(recent.filters.searchTags).toBeUndefined();
    expect(graph.filters.location).toEqual([]);
    expect(recent.filters.location).toEqual([]);
  });
});
