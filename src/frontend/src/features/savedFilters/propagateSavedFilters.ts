import type { UnknownAction } from '@reduxjs/toolkit';
import type { SavedFilters, KeywordList } from '../../types';
import { resolveActiveTags } from './resolveActiveTags';
import {
  setGraphTimeWindow,
  setGraphLocation,
  setGraphSearchTags,
} from '../filters/slices/graphFiltersSlice';
import {
  setRecentJobsTimeWindow,
  setRecentJobsLocation,
  setRecentJobsSearchTags,
} from '../filters/slices/recentJobsFiltersSlice';

/**
 * Build the redux actions that snap the Company (graph) and Recent Jobs filter
 * slices to a just-saved {@link SavedFilters}. Dispatching these mirrors what a
 * page refresh's one-shot hydration does, but on demand right after a save — so
 * saved-filter edits reach both pages without a refresh (the hydration guard in
 * `createFilterSlice` deliberately blocks re-hydration, so we push values via
 * the `set*` actions instead). The active keyword-list id is resolved to
 * concrete tags against `lists` (built-in included); `null` clears the filter.
 *
 * Locations are passed through unchanged (an empty array means "no location
 * filter", same as hydration), so propagation is byte-for-byte what a refresh
 * would produce.
 */
export function savedFiltersPropagationActions(
  saved: SavedFilters,
  lists: KeywordList[]
): UnknownAction[] {
  return [
    setGraphTimeWindow(saved.trendTimeWindow),
    setGraphLocation(saved.locations),
    setGraphSearchTags(resolveActiveTags(saved.trendActiveKeywordListId, lists)),
    setRecentJobsTimeWindow(saved.recentTimeWindow),
    setRecentJobsLocation(saved.locations),
    setRecentJobsSearchTags(resolveActiveTags(saved.recentActiveKeywordListId, lists)),
  ];
}

/**
 * Build the redux actions that re-push a just-edited keyword list's *contents*
 * into whichever filter pages currently have that list active. Companion to
 * {@link savedFiltersPropagationActions}, but scoped to search tags only: editing
 * a list's keywords changes neither the time windows nor the locations, and the
 * per-page active *selection* is unchanged, so only the resolved tags move.
 *
 * `activeIds` are the persisted per-page pointers (what each page is actually
 * filtering by), so a staged-but-unsaved selection change won't propagate. The
 * edited list's tags are passed through exactly as stored (include/exclude
 * preserved). Returns no actions when the edited list is active on neither page,
 * leaving those pages untouched.
 */
export function activeListContentPropagationActions(
  editedList: KeywordList,
  activeIds: Pick<SavedFilters, 'recentActiveKeywordListId' | 'trendActiveKeywordListId'>
): UnknownAction[] {
  const tags = editedList.tags.map((tag) => ({ ...tag }));
  const actions: UnknownAction[] = [];
  if (activeIds.trendActiveKeywordListId === editedList.id) {
    actions.push(setGraphSearchTags(tags));
  }
  if (activeIds.recentActiveKeywordListId === editedList.id) {
    actions.push(setRecentJobsSearchTags(tags));
  }
  return actions;
}

/**
 * Build the redux actions that clear a just-deleted keyword list's tags from
 * whichever filter pages currently have that list active. The delete counterpart
 * to {@link activeListContentPropagationActions}: a deleted list can no longer be
 * resolved to tags, so each page that was filtering by it is reset to "no keyword
 * filter" (`setSearchTags(undefined)`), matching what hydration produces for a
 * null active pointer.
 *
 * `activeIds` are the persisted per-page pointers (what each page is actually
 * filtering by) — the backend NULLs them in the same delete transaction, so the
 * cleared filter stays in sync with the refetched saved filters. Returns no
 * actions when the deleted list is active on neither page, leaving them untouched.
 */
export function deletedListPropagationActions(
  deletedListId: string,
  activeIds: Pick<SavedFilters, 'recentActiveKeywordListId' | 'trendActiveKeywordListId'>
): UnknownAction[] {
  const actions: UnknownAction[] = [];
  if (activeIds.trendActiveKeywordListId === deletedListId) {
    actions.push(setGraphSearchTags(undefined));
  }
  if (activeIds.recentActiveKeywordListId === deletedListId) {
    actions.push(setRecentJobsSearchTags(undefined));
  }
  return actions;
}
