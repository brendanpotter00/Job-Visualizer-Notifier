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
