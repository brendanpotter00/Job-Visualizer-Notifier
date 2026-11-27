import type { SearchTag } from '../../types';
import { TIME_WINDOW_DURATIONS } from '../../constants/time';
import { RECENT_LIST_FIELDS, type DefaultSearch } from './defaultSearch';

/**
 * A default search a signed-out reader asked to save, carried across the sign-in
 * redirect.
 *
 * sessionStorage, not the URL: the Recent URL has no specialty param, so the
 * URL cannot carry the whole search. sessionStorage belongs to one tab, so a
 * sign-in finished in another tab (or blocked storage) loses it; the click still
 * goes to sign-in, the search is just not saved.
 *
 * Read ONCE per page load into a module memo, like `features/auth/returnTo.ts`.
 * `hadPendingDefaultSearchAtLoad` stays true for the whole load even after the
 * pending search is cleared, so the first-sign-in questions cannot reopen
 * mid-load.
 */

export const PENDING_DEFAULT_SEARCH_KEY = 'jvn.pendingDefaultSearch.v1';
export const PENDING_DEFAULT_SEARCH_TTL_MS = 30 * 60 * 1000;

interface StoredPending {
  v: 1;
  savedAt: number;
  search: DefaultSearch;
}

function sessionStore(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === 'string');

function isSearchTag(value: unknown): value is SearchTag {
  if (value === null || typeof value !== 'object') return false;
  const tag = value as Record<string, unknown>;
  return typeof tag.text === 'string' && (tag.mode === 'include' || tag.mode === 'exclude');
}

function parseSearch(value: unknown): DefaultSearch | null {
  if (value === null || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  if (
    typeof raw.timeWindow !== 'string' ||
    !Object.prototype.hasOwnProperty.call(TIME_WINDOW_DURATIONS, raw.timeWindow)
  ) {
    return null;
  }
  if (!Array.isArray(raw.searchTags) || !raw.searchTags.every(isSearchTag)) return null;
  for (const row of RECENT_LIST_FIELDS) {
    if (!isStringArray(raw[row.filter])) return null;
  }
  return raw as unknown as DefaultSearch;
}

/** Validate a stored value: right version, not expired, a well-formed search. */
export function parsePendingDefaultSearch(raw: string | null, now: number): DefaultSearch | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (value === null || typeof value !== 'object') return null;
  const stored = value as Record<string, unknown>;
  if (stored.v !== 1 || typeof stored.savedAt !== 'number') return null;
  const age = now - stored.savedAt;
  if (age < 0 || age > PENDING_DEFAULT_SEARCH_TTL_MS) return null;
  return parseSearch(stored.search);
}

/** Remember `search` for the page load after sign-in. False when storage is unavailable. */
export function writePendingDefaultSearch(search: DefaultSearch, now = Date.now()): boolean {
  const store = sessionStore();
  if (!store) return false;
  const stored: StoredPending = { v: 1, savedAt: now, search };
  try {
    store.setItem(PENDING_DEFAULT_SEARCH_KEY, JSON.stringify(stored));
    return true;
  } catch {
    return false;
  }
}

let memo: { search: DefaultSearch | null; had: boolean } | null = null;

/**
 * The pending search found when this page loaded, or null. Read and validated
 * once; an expired or malformed value is removed. Null after
 * {@link clearPendingDefaultSearch}.
 */
export function pendingDefaultSearchAtLoad(now = Date.now()): DefaultSearch | null {
  if (memo) return memo.search;
  const store = sessionStore();
  let raw: string | null = null;
  try {
    raw = store?.getItem(PENDING_DEFAULT_SEARCH_KEY) ?? null;
  } catch {
    raw = null;
  }
  const search = parsePendingDefaultSearch(raw, now);
  if (raw !== null && search === null) {
    try {
      store?.removeItem(PENDING_DEFAULT_SEARCH_KEY);
    } catch {
      // Unreadable storage: nothing to clean up.
    }
  }
  memo = { search, had: search !== null };
  return search;
}

/** Whether this page load started with a pending search. Stays true after a clear. */
export function hadPendingDefaultSearchAtLoad(): boolean {
  pendingDefaultSearchAtLoad();
  return memo?.had ?? false;
}

/** Drop the pending search (storage and this load's memo). */
export function clearPendingDefaultSearch(): void {
  try {
    sessionStore()?.removeItem(PENDING_DEFAULT_SEARCH_KEY);
  } catch {
    // Storage gone: there is nothing left to clear.
  }
  if (memo) memo.search = null;
}

/** Tests only: forget the memo, as a new page load would. */
export function resetPendingDefaultSearchForTests(): void {
  memo = null;
}
