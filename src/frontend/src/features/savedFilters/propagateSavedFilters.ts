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
 *
 * `options.listsLoaded` (default true) guards the search-tag actions: pass
 * `false` when the keyword-lists cache has not resolved yet, so a non-null
 * active pointer that can't be resolved to tags is NOT propagated as a spurious
 * `setSearchTags(undefined)` clear (the propagate-on-save keyword-wipe bug). An
 * intentional `null` pointer is always propagated (it clears the filter on
 * purpose); the time-window/location values always propagate either way.
 */
export function savedFiltersPropagationActions(
  saved: SavedFilters,
  lists: KeywordList[],
  options: { listsLoaded?: boolean } = {}
): UnknownAction[] {
  // When the keyword-lists cache hasn't loaded yet, `lists` is empty for a
  // reason orthogonal to the user's intent: we simply can't resolve a non-null
  // active pointer to its tags. Emitting `setSearchTags(undefined)` in that case
  // would clear a live keyword filter for a list that still exists (the
  // propagate-on-save keyword-wipe bug). So when lists are NOT loaded we still
  // propagate the time-window / location values, but skip the search-tag action
  // for any page whose active pointer is non-null (unresolvable-because-not-
  // loaded, distinct from an intentional `null` clear, which we DO propagate).
  const { listsLoaded = true } = options;

  const actions: UnknownAction[] = [
    setGraphTimeWindow(saved.trendTimeWindow),
    setGraphLocation(saved.locations),
  ];
  if (listsLoaded || saved.trendActiveKeywordListId === null) {
    actions.push(setGraphSearchTags(resolveActiveTags(saved.trendActiveKeywordListId, lists)));
  }
  actions.push(
    setRecentJobsTimeWindow(saved.recentTimeWindow),
    setRecentJobsLocation(saved.locations)
  );
  if (listsLoaded || saved.recentActiveKeywordListId === null) {
    actions.push(
      setRecentJobsSearchTags(resolveActiveTags(saved.recentActiveKeywordListId, lists))
    );
  }
  return actions;
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
