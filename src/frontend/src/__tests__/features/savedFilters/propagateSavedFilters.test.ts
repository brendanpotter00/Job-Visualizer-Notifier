import { describe, it, expect } from 'vitest';
import graphReducer, {
  setGraphSearchTags,
  setGraphTimeWindow,
} from '../../../features/filters/slices/graphFiltersSlice';
import recentJobsReducer, {
  setRecentJobsSearchTags,
  setRecentJobsTimeWindow,
} from '../../../features/filters/slices/recentJobsFiltersSlice';
import {
  savedFiltersPropagationActions,
  activeListContentPropagationActions,
} from '../../../features/savedFilters/propagateSavedFilters';
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

/** Apply content-propagation actions to both reducers from a seeded base state. */
function applyContentPropagation(
  editedList: KeywordList,
  activeIds: Pick<SavedFilters, 'recentActiveKeywordListId' | 'trendActiveKeywordListId'>
) {
  // Seed both slices with stale tags + an untouched time window so we can prove
  // only the search tags of the active page move.
  const seed = { text: 'stale', mode: 'include' as const };
  let graph = graphReducer(undefined, setGraphSearchTags([seed]));
  graph = graphReducer(graph, setGraphTimeWindow('90d'));
  let recent = recentJobsReducer(undefined, setRecentJobsSearchTags([seed]));
  recent = recentJobsReducer(recent, setRecentJobsTimeWindow('90d'));

  const actions = activeListContentPropagationActions(editedList, activeIds);
  for (const action of actions) {
    graph = graphReducer(graph, action);
    recent = recentJobsReducer(recent, action);
  }
  return { graph, recent, actions };
}

describe('activeListContentPropagationActions (live content-edit propagation)', () => {
  const edited: KeywordList = {
    id: 'list-1',
    name: 'Backend',
    isBuiltin: false,
    position: 0,
    tags: [
      { text: 'golang', mode: 'include' },
      { text: 'intern', mode: 'exclude' },
    ],
  };

  it('pushes the edited tags to both pages when the list is active on both', () => {
    const { graph, recent } = applyContentPropagation(edited, {
      recentActiveKeywordListId: 'list-1',
      trendActiveKeywordListId: 'list-1',
    });

    expect(graph.filters.searchTags).toEqual(edited.tags);
    expect(recent.filters.searchTags).toEqual(edited.tags);
    // Include/exclude preserved; time windows untouched.
    expect(graph.filters.timeWindow).toBe('90d');
    expect(recent.filters.timeWindow).toBe('90d');
  });

  it('updates only the page the edited list is active on, leaving the other stale', () => {
    const { graph, recent, actions } = applyContentPropagation(edited, {
      recentActiveKeywordListId: 'list-1',
      trendActiveKeywordListId: 'other-list',
    });

    expect(recent.filters.searchTags).toEqual(edited.tags);
    // Company (graph/trend) page has a different active list — left untouched.
    expect(graph.filters.searchTags).toEqual([{ text: 'stale', mode: 'include' }]);
    expect(actions).toHaveLength(1);
  });

  it('emits no actions when the edited list is active on neither page', () => {
    const { graph, recent, actions } = applyContentPropagation(edited, {
      recentActiveKeywordListId: null,
      trendActiveKeywordListId: 'other-list',
    });

    expect(actions).toEqual([]);
    expect(graph.filters.searchTags).toEqual([{ text: 'stale', mode: 'include' }]);
    expect(recent.filters.searchTags).toEqual([{ text: 'stale', mode: 'include' }]);
  });
});
