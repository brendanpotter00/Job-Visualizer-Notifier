import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { Provider } from 'react-redux';
import { createTestStore } from '../../../test/testUtils';
import type { KeywordList, SavedFilters, SearchTag } from '../../../types';
import type { DefaultSearch } from '../../../features/defaultSearch/defaultSearch';

const { createMock, updateListMock, putMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  updateListMock: vi.fn(),
  putMock: vi.fn(),
}));

// The three mutations are stubbed the way SavedFiltersPage.categoryLevel.test.tsx
// stubs them; the real API object stays, so the cache writes run for real.
vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useCreateKeywordListMutation: () => [createMock, { isLoading: false }],
    useUpdateKeywordListMutation: () => [updateListMock, { isLoading: false }],
    useUpdateSavedFiltersMutation: () => [putMock, { isLoading: false }],
  };
});

const { savedFiltersApi } = await import('../../../features/savedFilters/savedFiltersApi');
const { useSaveDefaultSearch, SAVE_DEFAULT_SEARCH_ERROR, TOO_MANY_KEYWORD_LISTS_ERROR } =
  await import('../../../features/defaultSearch/useSaveDefaultSearch');

const inc = (text: string): SearchTag => ({ text, mode: 'include' });
const ok = <T,>(value: T) => ({ unwrap: () => Promise.resolve(value) });
const fail = (status: number) => ({ unwrap: () => Promise.reject({ status, data: {} }) });

const BUILTIN: KeywordList = {
  id: 'builtin-swe',
  name: 'Software Engineering',
  tags: [inc('software engineer')],
  isBuiltin: true,
  position: 99,
};

const CURRENT: SavedFilters = {
  recentTimeWindow: 'all',
  trendTimeWindow: '30d',
  locations: [],
  category: [],
  level: [],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

function search(overrides: Partial<DefaultSearch> = {}): DefaultSearch {
  return {
    timeWindow: '24h',
    searchTags: [],
    location: ['San Francisco, CA, US'],
    category: ['software_engineering'],
    level: ['entry'],
    subcategory: ['backend'],
    companyCategory: [],
    ...overrides,
  };
}

/** The PUT answers with exactly what it was sent, like the server. */
function echoPut() {
  putMock.mockImplementation((body: SavedFilters) => ok(body));
}

async function setup(lists: KeywordList[] = [BUILTIN]) {
  const store = createTestStore();
  await store.dispatch(savedFiltersApi.util.upsertQueryData('getSavedFilters', undefined, CURRENT));
  await store.dispatch(savedFiltersApi.util.upsertQueryData('getKeywordLists', undefined, lists));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Provider store={store}>{children}</Provider>
  );
  const { result } = renderHook(() => useSaveDefaultSearch(), { wrapper });
  const save = async (s: DefaultSearch, ctxLists = lists) => {
    let ok = false;
    await act(async () => {
      ok = await result.current.save(s, { current: CURRENT, lists: ctxLists });
    });
    return ok;
  };
  return { store, save };
}

const cachedLists = (store: ReturnType<typeof createTestStore>) =>
  savedFiltersApi.endpoints.getKeywordLists.select()(store.getState()).data;
const cachedSaved = (store: ReturnType<typeof createTestStore>) =>
  savedFiltersApi.endpoints.getSavedFilters.select()(store.getState()).data;

beforeEach(() => {
  createMock.mockReset();
  updateListMock.mockReset();
  putMock.mockReset();
  echoPut();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useSaveDefaultSearch', () => {
  it('no keywords: no list call, both pointers null', async () => {
    const { save } = await setup();
    expect(await save(search())).toBe(true);
    expect(createMock).not.toHaveBeenCalled();
    expect(updateListMock).not.toHaveBeenCalled();
    expect(putMock).toHaveBeenCalledWith({
      recentTimeWindow: '24h',
      trendTimeWindow: '30d',
      locations: ['San Francisco, CA, US'],
      category: ['software_engineering'],
      level: ['entry'],
      subcategory: ['backend'],
      recentActiveKeywordListId: null,
      trendActiveKeywordListId: null,
    });
  });

  it('reuses a list that already has exactly these keywords (the built-in here)', async () => {
    const { save } = await setup();
    await save(search({ searchTags: [inc('software engineer')] }));
    expect(createMock).not.toHaveBeenCalled();
    expect(updateListMock).not.toHaveBeenCalled();
    expect(putMock.mock.calls[0][0]).toMatchObject({
      recentActiveKeywordListId: 'builtin-swe',
      trendActiveKeywordListId: 'builtin-swe',
    });
  });

  it('creates the "Default search" list, then PUTs with its id', async () => {
    const created: KeywordList = {
      id: 'new-1',
      name: 'Default search',
      tags: [inc('rust')],
      isBuiltin: false,
      position: 0,
    };
    createMock.mockReturnValue(ok(created));
    const { store, save } = await setup();
    await save(search({ searchTags: [inc('rust')] }));
    expect(createMock).toHaveBeenCalledWith({ name: 'Default search', tags: [inc('rust')] });
    expect(putMock.mock.calls[0][0]).toMatchObject({
      recentActiveKeywordListId: 'new-1',
      trendActiveKeywordListId: 'new-1',
    });
    // The new list is in the cache, before the built-in, so the button reads
    // "unchanged" without waiting for the refetch.
    expect(cachedLists(store)?.map((l) => l.id)).toEqual(['new-1', 'builtin-swe']);
  });

  it('PATCHes an existing "Default search" list', async () => {
    const own: KeywordList = {
      id: 'own',
      name: 'Default search',
      tags: [inc('old')],
      isBuiltin: false,
      position: 0,
    };
    updateListMock.mockReturnValue(ok({ ...own, tags: [inc('rust')] }));
    const { store, save } = await setup([own, BUILTIN]);
    await save(search({ searchTags: [inc('rust')] }));
    expect(createMock).not.toHaveBeenCalled();
    expect(updateListMock).toHaveBeenCalledWith({ id: 'own', tags: [inc('rust')] });
    expect(putMock.mock.calls[0][0]).toMatchObject({ recentActiveKeywordListId: 'own' });
    expect(cachedLists(store)?.find((l) => l.id === 'own')?.tags).toEqual([inc('rust')]);
  });

  it('a POST 409 refetches the lists once, then PATCHes the list it missed', async () => {
    const missed: KeywordList = {
      id: 'missed',
      name: 'Default Search',
      tags: [inc('old')],
      isBuiltin: false,
      position: 3,
    };
    createMock.mockReturnValue(fail(409));
    updateListMock.mockReturnValue(ok({ ...missed, tags: [inc('rust')] }));
    const { save } = await setup();
    // After setup: the cache seeding goes through `initiate` too.
    const initiate = vi
      .spyOn(savedFiltersApi.endpoints.getKeywordLists, 'initiate')
      .mockReturnValue((() => ok([missed, BUILTIN])) as never);
    expect(await save(search({ searchTags: [inc('rust')] }))).toBe(true);
    expect(initiate).toHaveBeenCalledTimes(1);
    expect(initiate.mock.calls[0][1]).toMatchObject({ forceRefetch: true, subscribe: false });
    expect(updateListMock).toHaveBeenCalledWith({ id: 'missed', tags: [inc('rust')] });
    expect(putMock.mock.calls[0][0]).toMatchObject({ recentActiveKeywordListId: 'missed' });
  });

  it('a POST 422 (the list cap) fails with the cap message and sends no PUT', async () => {
    createMock.mockReturnValue(fail(422));
    const { store, save } = await setup();
    expect(await save(search({ searchTags: [inc('rust')] }))).toBe(false);
    expect(putMock).not.toHaveBeenCalled();
    expect(store.getState().defaultSearch).toMatchObject({
      saving: false,
      result: { kind: 'error', message: TOO_MANY_KEYWORD_LISTS_ERROR },
    });
  });

  it('a failed PUT records the error and leaves the caches alone', async () => {
    putMock.mockReturnValue(fail(500));
    const { store, save } = await setup();
    const graphBefore = store.getState().graphFilters;
    expect(await save(search())).toBe(false);
    expect(store.getState().defaultSearch.result).toMatchObject({
      kind: 'error',
      message: SAVE_DEFAULT_SEARCH_ERROR,
    });
    expect(cachedSaved(store)).toEqual(CURRENT);
    expect(store.getState().graphFilters).toBe(graphBefore);
  });

  it('on success: caches written, Companies filters moved (not its window), Recent untouched', async () => {
    const { store, save } = await setup();
    const recentBefore = store.getState().recentJobsFilters;
    const graphWindowBefore = store.getState().graphFilters.filters.timeWindow;
    const s = search({ searchTags: [inc('software engineer')] });
    await save(s);

    expect(cachedSaved(store)).toMatchObject({ recentTimeWindow: '24h', level: ['entry'] });
    const graph = store.getState().graphFilters.filters;
    expect(graph.location).toEqual(['San Francisco, CA, US']);
    expect(graph.category).toEqual(['software_engineering']);
    expect(graph.level).toEqual(['entry']);
    expect(graph.subcategory).toEqual(['backend']);
    expect(graph.searchTags).toEqual([inc('software engineer')]);
    expect(graph.timeWindow).toBe(graphWindowBefore);
    expect(store.getState().recentJobsFilters).toBe(recentBefore);
    expect(store.getState().defaultSearch).toMatchObject({
      saving: false,
      result: { kind: 'saved' },
    });
  });
});
