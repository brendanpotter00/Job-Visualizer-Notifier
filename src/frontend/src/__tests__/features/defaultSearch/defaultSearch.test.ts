import { describe, it, expect } from 'vitest';
import {
  DEFAULT_SEARCH_LIST_NAME,
  RECENT_LIST_FIELDS,
  defaultSearchFromFilters,
  defaultSearchFromSaved,
  isSameDefaultSearch,
  planKeywordList,
  toOnboardingAnswers,
  toRecentFiltersPatch,
  toSavedFiltersPayload,
  type DefaultSearch,
} from '../../../features/defaultSearch/defaultSearch';
import { recentJobsInitialFilters } from '../../../features/filters/slices/recentJobsFiltersSlice';
import type { KeywordList, RecentJobsFilters, SavedFilters, SearchTag } from '../../../types';

const inc = (text: string): SearchTag => ({ text, mode: 'include' });
const exc = (text: string): SearchTag => ({ text, mode: 'exclude' });

function filters(overrides: Partial<RecentJobsFilters> = {}): RecentJobsFilters {
  return { ...recentJobsInitialFilters, ...overrides };
}

const same = (a: Partial<RecentJobsFilters>, b: Partial<RecentJobsFilters>) =>
  isSameDefaultSearch(defaultSearchFromFilters(filters(a)), defaultSearchFromFilters(filters(b)));

/**
 * Mirror of the backend's `saved_filters_service.default_saved_filters()` as the
 * API serializes it: what `GET /api/users/saved-filters` answers for a reader
 * who never saved anything.
 */
const SERVER_NO_ROW: SavedFilters = {
  recentTimeWindow: 'all',
  trendTimeWindow: '90d',
  locations: [],
  category: [],
  level: [],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

const BUILTIN: KeywordList = {
  id: 'builtin-swe',
  name: 'Software Engineering',
  tags: [inc('software engineer'), inc('developer')],
  isBuiltin: true,
  position: 99,
};

function list(id: string, name: string, tags: SearchTag[], position: number): KeywordList {
  return { id, name, tags, isBuiltin: false, position };
}

describe('defaultSearch — equality', () => {
  it.each(RECENT_LIST_FIELDS.map((row) => row.filter))('%s: undefined equals []', (field) => {
    expect(same({ [field]: undefined }, { [field]: [] })).toBe(true);
  });

  it.each(RECENT_LIST_FIELDS.map((row) => row.filter))('%s: order is ignored', (field) => {
    expect(same({ [field]: ['a', 'b'] }, { [field]: ['b', 'a'] })).toBe(true);
  });

  it.each(RECENT_LIST_FIELDS.map((row) => row.filter))('%s: duplicates collapse', (field) => {
    expect(same({ [field]: ['a', 'a', 'b'] }, { [field]: ['b', 'a'] })).toBe(true);
  });

  it.each(RECENT_LIST_FIELDS.map((row) => row.filter))('%s: a different value differs', (field) => {
    expect(same({ [field]: ['a'] }, { [field]: ['b'] })).toBe(false);
    expect(same({ [field]: ['a'] }, { [field]: undefined })).toBe(false);
  });

  it('keywords: order is ignored, undefined equals []', () => {
    expect(same({ searchTags: [inc('a'), exc('b')] }, { searchTags: [exc('b'), inc('a')] })).toBe(
      true
    );
    expect(same({ searchTags: undefined }, { searchTags: [] })).toBe(true);
  });

  it('keywords: the same text with another mode differs', () => {
    expect(same({ searchTags: [inc('senior')] }, { searchTags: [exc('senior')] })).toBe(false);
  });

  it('keywords: text is case-sensitive', () => {
    expect(same({ searchTags: [inc('Backend')] }, { searchTags: [inc('backend')] })).toBe(false);
  });

  it('the time window must match exactly', () => {
    expect(same({ timeWindow: '24h' }, { timeWindow: '24h' })).toBe(true);
    expect(same({ timeWindow: '24h' }, { timeWindow: '7d' })).toBe(false);
  });

  it('ignores the dead softwareOnly and employmentType fields', () => {
    expect(same({ softwareOnly: true, employmentType: 'Full-time' }, {})).toBe(true);
  });

  it('a reader who never saved sees the site defaults as their saved default', () => {
    // The button must start grayed out for a brand-new account: the server's
    // no-row answer and the slice's initial state are the same default.
    expect(
      isSameDefaultSearch(
        defaultSearchFromSaved(SERVER_NO_ROW, [BUILTIN]),
        defaultSearchFromFilters(recentJobsInitialFilters)
      )
    ).toBe(true);
  });
});

describe('defaultSearch — reading a saved row', () => {
  it('resolves the built-in pointer to its tags', () => {
    const search = defaultSearchFromSaved(
      { ...SERVER_NO_ROW, recentActiveKeywordListId: 'builtin-swe' },
      [BUILTIN]
    );
    expect(search.searchTags).toEqual(BUILTIN.tags);
  });

  it('reads a pointer to a missing list as no keywords', () => {
    const search = defaultSearchFromSaved(
      { ...SERVER_NO_ROW, recentActiveKeywordListId: 'gone' },
      [BUILTIN]
    );
    expect(search.searchTags).toEqual([]);
  });

  it('reads the RECENT window and pointer, never the trend ones', () => {
    const search = defaultSearchFromSaved(
      {
        ...SERVER_NO_ROW,
        recentTimeWindow: '24h',
        trendTimeWindow: '30d',
        trendActiveKeywordListId: 'builtin-swe',
      },
      [BUILTIN]
    );
    expect(search.timeWindow).toBe('24h');
    expect(search.searchTags).toEqual([]);
  });

  it('maps every saved column to its filter', () => {
    const search = defaultSearchFromSaved(
      {
        ...SERVER_NO_ROW,
        locations: ['San Francisco, CA, US'],
        category: ['software_engineering'],
        level: ['entry'],
        subcategory: ['backend'],
      },
      []
    );
    expect(search).toMatchObject({
      location: ['San Francisco, CA, US'],
      category: ['software_engineering'],
      level: ['entry'],
      subcategory: ['backend'],
    });
  });
});

describe('defaultSearch — the field map', () => {
  it('has a row for every list field of the Recent slice', () => {
    // A new list filter on the Recent slice (feature B's companyCategory, say)
    // must get a row, or it would be neither compared nor saved.
    const listFields = Object.entries(recentJobsInitialFilters)
      .filter(([key, value]) => key !== 'searchTags' && (value === undefined || Array.isArray(value)))
      .map(([key]) => key)
      .filter((key) => key !== 'employmentType');
    expect(RECENT_LIST_FIELDS.map((row) => row.filter).sort()).toEqual(listFields.sort());
  });
});

describe('toSavedFiltersPayload', () => {
  const search: DefaultSearch = {
    timeWindow: '24h',
    searchTags: [inc('rust')],
    location: ['Remote (US)'],
    category: ['software_engineering'],
    level: ['senior'],
    subcategory: ['backend'],
    companyCategory: [],
  };
  const current: SavedFilters = {
    ...SERVER_NO_ROW,
    recentTimeWindow: '7d',
    trendTimeWindow: '30d',
    locations: ['New York, NY, US'],
    recentActiveKeywordListId: 'old',
    trendActiveKeywordListId: 'other',
  };

  it('keeps the trend window, sets both pointers, and takes the rest from the search', () => {
    expect(toSavedFiltersPayload(search, current, 'list-1')).toEqual({
      recentTimeWindow: '24h',
      trendTimeWindow: '30d',
      locations: ['Remote (US)'],
      category: ['software_engineering'],
      level: ['senior'],
      subcategory: ['backend'],
      recentActiveKeywordListId: 'list-1',
      trendActiveKeywordListId: 'list-1',
    });
  });

  it('sends every saved-filters key (the PUT replaces the whole row)', () => {
    expect(Object.keys(toSavedFiltersPayload(search, current, null)).sort()).toEqual(
      Object.keys(SERVER_NO_ROW).sort()
    );
  });

  it('round-trips: the saved row reads back as the same search', () => {
    const lists = [list('list-1', DEFAULT_SEARCH_LIST_NAME, [inc('rust')], 0)];
    const saved = toSavedFiltersPayload(search, current, 'list-1');
    expect(isSameDefaultSearch(defaultSearchFromSaved(saved, lists), search)).toBe(true);
  });
});

describe('toRecentFiltersPatch', () => {
  it('turns empty lists into "no filter"', () => {
    expect(toRecentFiltersPatch(defaultSearchFromFilters(recentJobsInitialFilters))).toEqual({
      timeWindow: 'all',
      searchTags: undefined,
      location: undefined,
      category: undefined,
      level: undefined,
      subcategory: undefined,
    });
  });

  it('copies the values', () => {
    const search = defaultSearchFromFilters(
      filters({ timeWindow: '3d', searchTags: [inc('go')], level: ['entry'] })
    );
    expect(toRecentFiltersPatch(search)).toMatchObject({
      timeWindow: '3d',
      searchTags: [inc('go')],
      level: ['entry'],
    });
  });
});

describe('toOnboardingAnswers', () => {
  it('maps location to locations', () => {
    const search = defaultSearchFromFilters(
      filters({ category: ['software_engineering'], subcategory: ['backend'], level: ['entry'], location: ['Austin, TX, US'] })
    );
    expect(toOnboardingAnswers(search)).toEqual({
      category: ['software_engineering'],
      subcategory: ['backend'],
      level: ['entry'],
      locations: ['Austin, TX, US'],
      companyCategory: [],
    });
  });

  it('drops a specialty without Software Engineering', () => {
    const search = defaultSearchFromFilters(
      filters({ category: ['product_manager'], subcategory: ['backend'] })
    );
    expect(toOnboardingAnswers(search).subcategory).toEqual([]);
  });
});

describe('planKeywordList', () => {
  const mine = list('mine', 'Mine', [inc('rust'), exc('senior')], 0);
  const later = list('later', 'Later', [inc('rust'), exc('senior')], 1);
  const defaultList = list('dflt', '  default SEARCH ', [inc('old')], 2);

  it('no keywords → no list', () => {
    expect(planKeywordList([], 'mine', [mine])).toEqual({ kind: 'none' });
  });

  it('reuses the current list when it has exactly these keywords, in any order', () => {
    expect(planKeywordList([exc('senior'), inc('rust')], 'later', [mine, later])).toEqual({
      kind: 'reuse',
      id: 'later',
    });
  });

  it('else reuses the first matching user list by position', () => {
    expect(planKeywordList([inc('rust'), exc('senior')], null, [later, mine])).toEqual({
      kind: 'reuse',
      id: 'mine',
    });
  });

  it('reuses the built-in list after the user lists', () => {
    expect(planKeywordList(BUILTIN.tags, null, [mine, BUILTIN])).toEqual({
      kind: 'reuse',
      id: 'builtin-swe',
    });
  });

  it('a different mode is not a match', () => {
    expect(planKeywordList([inc('rust'), inc('senior')], 'mine', [mine])).toEqual({
      kind: 'create',
    });
  });

  it('PATCHes the "Default search" list (trimmed, any case)', () => {
    expect(planKeywordList([inc('new')], null, [mine, defaultList, BUILTIN])).toEqual({
      kind: 'update',
      id: 'dflt',
    });
  });

  it('never PATCHes the built-in, even if it were named "Default search"', () => {
    const builtinNamed = { ...BUILTIN, name: DEFAULT_SEARCH_LIST_NAME };
    expect(planKeywordList([inc('new')], null, [builtinNamed])).toEqual({ kind: 'create' });
  });

  it('otherwise creates the list', () => {
    expect(planKeywordList([inc('new')], 'mine', [mine, BUILTIN])).toEqual({ kind: 'create' });
  });
});

describe('company types in the default search', () => {
  const base: DefaultSearch = {
    timeWindow: 'all',
    searchTags: [],
    location: [],
    category: [],
    level: [],
    subcategory: [],
    companyCategory: [],
  };
  const current: SavedFilters = {
    recentTimeWindow: 'all',
    trendTimeWindow: '90d',
    locations: [],
    category: [],
    level: [],
    subcategory: [],
    recentActiveKeywordListId: null,
    trendActiveKeywordListId: null,
  };

  it('counts a company type change as a change, compared as a set', () => {
    expect(isSameDefaultSearch(base, { ...base, companyCategory: ['fintech'] })).toBe(false);
    expect(
      isSameDefaultSearch(
        { ...base, companyCategory: ['big_tech', 'fintech'] },
        { ...base, companyCategory: ['fintech', 'big_tech'] }
      )
    ).toBe(true);
  });

  it('reads a saved row without companyCategory (an older backend) as no company type', () => {
    expect(defaultSearchFromSaved(current, []).companyCategory).toEqual([]);
    expect(defaultSearchFromSaved({ ...current, companyCategory: ['ai_labs'] }, []).companyCategory).toEqual([
      'ai_labs',
    ]);
  });

  it('sends company types only when the saved-filters GET carried them', () => {
    const search = { ...base, companyCategory: ['fintech'] };
    expect(toSavedFiltersPayload(search, current, null)).not.toHaveProperty('companyCategory');
    expect(toSavedFiltersPayload(search, { ...current, companyCategory: [] }, null).companyCategory).toEqual([
      'fintech',
    ]);
  });

  it('carries company types into the first-sign-in answers', () => {
    expect(toOnboardingAnswers({ ...base, companyCategory: ['ai_labs'] }).companyCategory).toEqual(['ai_labs']);
  });

  it('puts company types back on screen, empty as no filter', () => {
    expect(toRecentFiltersPatch({ ...base, companyCategory: ['fintech'] }).companyCategory).toEqual(['fintech']);
    expect(toRecentFiltersPatch(base).companyCategory).toBeUndefined();
  });
});
