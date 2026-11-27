import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  PENDING_DEFAULT_SEARCH_KEY,
  PENDING_DEFAULT_SEARCH_TTL_MS,
  clearPendingDefaultSearch,
  hadPendingDefaultSearchAtLoad,
  pendingDefaultSearchAtLoad,
  resetPendingDefaultSearchForTests,
  writePendingDefaultSearch,
} from '../../../features/defaultSearch/pendingDefaultSearch';
import type { DefaultSearch } from '../../../features/defaultSearch/defaultSearch';

const SEARCH: DefaultSearch = {
  timeWindow: '24h',
  searchTags: [{ text: 'rust', mode: 'include' }],
  location: ['San Francisco, CA, US'],
  category: ['software_engineering'],
  level: ['entry'],
  subcategory: ['backend'],
  companyCategory: ['fintech'],
};

const NOW = 1_800_000_000_000;

beforeEach(() => {
  window.sessionStorage.clear();
  resetPendingDefaultSearchForTests();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('pendingDefaultSearch', () => {
  it('round-trips a search through sessionStorage', () => {
    expect(writePendingDefaultSearch(SEARCH, NOW)).toBe(true);
    expect(pendingDefaultSearchAtLoad(NOW + 1000)).toEqual(SEARCH);
    expect(hadPendingDefaultSearchAtLoad()).toBe(true);
  });

  it('is empty when nothing was written', () => {
    expect(pendingDefaultSearchAtLoad(NOW)).toBeNull();
    expect(hadPendingDefaultSearchAtLoad()).toBe(false);
  });

  it('drops a search older than 30 minutes, and removes it', () => {
    writePendingDefaultSearch(SEARCH, NOW);
    expect(pendingDefaultSearchAtLoad(NOW + PENDING_DEFAULT_SEARCH_TTL_MS + 1)).toBeNull();
    expect(window.sessionStorage.getItem(PENDING_DEFAULT_SEARCH_KEY)).toBeNull();
  });

  it('keeps a search right at the TTL', () => {
    writePendingDefaultSearch(SEARCH, NOW);
    expect(pendingDefaultSearchAtLoad(NOW + PENDING_DEFAULT_SEARCH_TTL_MS)).toEqual(SEARCH);
  });

  it.each([
    ['not JSON', '{nope'],
    ['a wrong version', JSON.stringify({ v: 2, savedAt: NOW, search: SEARCH })],
    ['a missing savedAt', JSON.stringify({ v: 1, search: SEARCH })],
    ['a future savedAt', JSON.stringify({ v: 1, savedAt: NOW + 60_000, search: SEARCH })],
    ['an unknown time window', JSON.stringify({ v: 1, savedAt: NOW, search: { ...SEARCH, timeWindow: 'toString' } })],
    ['a malformed tag', JSON.stringify({ v: 1, savedAt: NOW, search: { ...SEARCH, searchTags: [{ text: 'a', mode: 'maybe' }] } })],
    ['a missing list field', JSON.stringify({ v: 1, savedAt: NOW, search: { ...SEARCH, level: undefined } })],
  ])('drops %s', (_label, raw) => {
    window.sessionStorage.setItem(PENDING_DEFAULT_SEARCH_KEY, raw);
    expect(pendingDefaultSearchAtLoad(NOW)).toBeNull();
    expect(window.sessionStorage.getItem(PENDING_DEFAULT_SEARCH_KEY)).toBeNull();
  });

  it('reads a search stored before company types existed as no company type', () => {
    const { companyCategory: _dropped, ...older } = SEARCH;
    window.sessionStorage.setItem(
      PENDING_DEFAULT_SEARCH_KEY,
      JSON.stringify({ v: 1, savedAt: NOW, search: older })
    );
    expect(pendingDefaultSearchAtLoad(NOW)).toEqual({ ...SEARCH, companyCategory: [] });
  });

  it('reads storage once per load', () => {
    expect(pendingDefaultSearchAtLoad(NOW)).toBeNull();
    // Written later in the same load (the signed-out click): not this load's.
    writePendingDefaultSearch(SEARCH, NOW);
    expect(pendingDefaultSearchAtLoad(NOW)).toBeNull();
    // The next load sees it.
    resetPendingDefaultSearchForTests();
    expect(pendingDefaultSearchAtLoad(NOW)).toEqual(SEARCH);
  });

  it('a clear empties storage and the memo, but the load still HAD one', () => {
    writePendingDefaultSearch(SEARCH, NOW);
    expect(pendingDefaultSearchAtLoad(NOW)).toEqual(SEARCH);
    clearPendingDefaultSearch();
    expect(pendingDefaultSearchAtLoad(NOW)).toBeNull();
    expect(window.sessionStorage.getItem(PENDING_DEFAULT_SEARCH_KEY)).toBeNull();
    expect(hadPendingDefaultSearchAtLoad()).toBe(true);
  });

  it('survives storage that throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    expect(writePendingDefaultSearch(SEARCH, NOW)).toBe(false);
    expect(pendingDefaultSearchAtLoad(NOW)).toBeNull();
    expect(hadPendingDefaultSearchAtLoad()).toBe(false);
    expect(() => clearPendingDefaultSearch()).not.toThrow();
  });
});
