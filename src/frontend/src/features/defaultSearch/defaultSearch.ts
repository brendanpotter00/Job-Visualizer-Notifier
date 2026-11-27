import type { KeywordList, RecentJobsFilters, SavedFilters, SearchTag, TimeWindow } from '../../types';
import type { OnboardingAnswers } from '../savedFilters/savedFiltersApi';
import { resolveActiveTags } from '../savedFilters/resolveActiveTags';
import { toRequestAnswers } from '../../components/onboarding/onboardingModel';

/**
 * "Save default search" on Recent Jobs: the Recent filters as ONE saved default.
 *
 * Pure. The button's dirty check and the save both go through this module, so
 * "what counts as a change" and "what gets saved" can never disagree.
 * Spike: `docs/implementations/save-default-search/SPIKE.md`.
 *
 * No backend change: typed keywords are kept in a keyword list named
 * {@link DEFAULT_SEARCH_LIST_NAME}, and both keyword pointers point at it.
 */

/** The keyword list that holds a default search's typed keywords. */
export const DEFAULT_SEARCH_LIST_NAME = 'Default search';

/**
 * THE field map: each list-valued Recent filter and the saved-filters column it
 * is stored in. The dirty check, the save, the restore after sign-in and the
 * `DefaultSearch` type are all built from this table, so a new list filter is
 * ONE row here (a unit test fails if a list field of the slice has no row).
 *
 * `searchTags` and `timeWindow` are not rows: keywords are saved as a pointer
 * to a keyword list, and the time window is the Recent page's own window.
 * `softwareOnly` and `employmentType` are dead fields and are never saved.
 */
export const RECENT_LIST_FIELDS = [
  { filter: 'location', saved: 'locations' },
  { filter: 'category', saved: 'category' },
  { filter: 'level', saved: 'level' },
  { filter: 'subcategory', saved: 'subcategory' },
  { filter: 'companyCategory', saved: 'companyCategory' },
] as const;

type RecentListField = (typeof RECENT_LIST_FIELDS)[number];
type ListFilterKey = RecentListField['filter'];
type ListSavedKey = RecentListField['saved'];

/** The Recent filters a default search holds, normalized (`undefined` is `[]`). */
export type DefaultSearch = {
  timeWindow: TimeWindow;
  searchTags: SearchTag[];
} & Record<ListFilterKey, string[]>;

const copyTags = (tags: readonly SearchTag[]): SearchTag[] =>
  tags.map((tag) => ({ text: tag.text, mode: tag.mode }));

function listFields(
  read: (row: RecentListField) => readonly string[] | undefined
): Record<ListFilterKey, string[]> {
  const out = {} as Record<ListFilterKey, string[]>;
  for (const row of RECENT_LIST_FIELDS) out[row.filter] = [...(read(row) ?? [])];
  return out;
}

/** The live Recent filters as a default search. */
export function defaultSearchFromFilters(filters: RecentJobsFilters): DefaultSearch {
  return {
    timeWindow: filters.timeWindow,
    searchTags: copyTags(filters.searchTags ?? []),
    ...listFields((row) => filters[row.filter]),
  };
}

/**
 * A saved row as a default search. The Recent keyword pointer is resolved to
 * its list's tags; a pointer to a list that no longer exists means no keywords,
 * exactly as hydration reads it.
 */
export function defaultSearchFromSaved(saved: SavedFilters, lists: KeywordList[]): DefaultSearch {
  return {
    timeWindow: saved.recentTimeWindow,
    searchTags: resolveActiveTags(saved.recentActiveKeywordListId, lists) ?? [],
    ...listFields((row) => saved[row.saved]),
  };
}

/** Sorted, de-duplicated: lists compare as sets. */
const sortedSet = (values: readonly string[]): string[] => [...new Set(values)].sort();

/** A keyword is its text AND its mode. Text is exact (case-sensitive), like the slice. */
const tagSet = (tags: readonly SearchTag[]): string[] =>
  sortedSet(tags.map((tag) => `${tag.mode}:${tag.text}`));

/**
 * The comparison key. Two searches are the same default exactly when their keys
 * are equal: lists compare as sets (order ignored, duplicates collapse), and the
 * time window must match.
 */
export function defaultSearchKey(search: DefaultSearch): string {
  return JSON.stringify([
    search.timeWindow,
    tagSet(search.searchTags),
    ...RECENT_LIST_FIELDS.map((row) => sortedSet(search[row.filter])),
  ]);
}

export function isSameDefaultSearch(a: DefaultSearch, b: DefaultSearch): boolean {
  return defaultSearchKey(a) === defaultSearchKey(b);
}

/**
 * The `PUT /api/users/saved-filters` body that saves `search`. The PUT replaces
 * the whole row, so every key is set: the Recent window and the list fields from
 * `search`, both keyword pointers to `listId`, and the Companies (trend) window
 * kept from `current`.
 */
export function toSavedFiltersPayload(
  search: DefaultSearch,
  current: SavedFilters,
  listId: string | null
): SavedFilters {
  const lists = {} as Record<ListSavedKey, string[]>;
  for (const row of RECENT_LIST_FIELDS) lists[row.saved] = [...search[row.filter]];
  const payload: SavedFilters = {
    recentTimeWindow: search.timeWindow,
    trendTimeWindow: current.trendTimeWindow,
    ...lists,
    recentActiveKeywordListId: listId,
    trendActiveKeywordListId: listId,
  };
  // An older backend (the Vercel-before-Railway deploy window) does not know
  // company types and 422s the unknown key. Its GET omits `companyCategory`, so
  // send the key only when the GET carried it; a PUT without it keeps the stored
  // value on a newer backend.
  if (current.companyCategory === undefined) delete payload.companyCategory;
  return payload;
}

/** The Recent slice patch that puts `search` back on screen (empty lists are "no filter"). */
export function toRecentFiltersPatch(search: DefaultSearch): Partial<RecentJobsFilters> {
  const patch: Partial<RecentJobsFilters> = {
    timeWindow: search.timeWindow,
    searchTags: search.searchTags.length ? copyTags(search.searchTags) : undefined,
  };
  for (const row of RECENT_LIST_FIELDS) {
    const values = search[row.filter];
    patch[row.filter] = values.length ? [...values] : undefined;
  }
  return patch;
}

/** The first-sign-in answers a default search stands for (a specialty only with SWE). */
export function toOnboardingAnswers(search: DefaultSearch): OnboardingAnswers {
  return toRequestAnswers({
    category: search.category,
    subcategory: search.subcategory,
    level: search.level,
    locations: search.location,
    companyCategory: search.companyCategory,
  });
}

/** What the save must do to get a keyword-list id for the search's keywords. */
export type KeywordListPlan =
  | { kind: 'none' }
  | { kind: 'reuse'; id: string }
  | { kind: 'update'; id: string }
  | { kind: 'create' };

const sameTags = (a: readonly SearchTag[], b: readonly SearchTag[]): boolean =>
  JSON.stringify(tagSet(a)) === JSON.stringify(tagSet(b));

/** A user list named "Default search" (trimmed, any case). Never the built-in. */
export function isDefaultSearchList(list: KeywordList): boolean {
  return !list.isBuiltin && list.name.trim().toLowerCase() === DEFAULT_SEARCH_LIST_NAME.toLowerCase();
}

/**
 * Pick the keyword list a save points at, in this order:
 * 1. no keywords → no list;
 * 2. the current pointer's list already has exactly these keywords → reuse it;
 * 3. another list has exactly these keywords → reuse it (user lists by position,
 *    then the built-in);
 * 4. the user has a "Default search" list → PATCH its keywords;
 * 5. otherwise → POST a new "Default search" list.
 *
 * The only list a save ever writes is the one named "Default search".
 */
export function planKeywordList(
  tags: readonly SearchTag[],
  currentId: string | null,
  lists: readonly KeywordList[]
): KeywordListPlan {
  if (tags.length === 0) return { kind: 'none' };

  const current = currentId === null ? undefined : lists.find((list) => list.id === currentId);
  if (current && sameTags(current.tags, tags)) return { kind: 'reuse', id: current.id };

  const ordered = [
    ...lists.filter((list) => !list.isBuiltin).sort((a, b) => a.position - b.position),
    ...lists.filter((list) => list.isBuiltin),
  ];
  const match = ordered.find((list) => sameTags(list.tags, tags));
  if (match) return { kind: 'reuse', id: match.id };

  const own = lists.find(isDefaultSearchList);
  if (own) return { kind: 'update', id: own.id };
  return { kind: 'create' };
}
