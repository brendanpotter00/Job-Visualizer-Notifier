import type { KeywordList, SearchTag } from '../../types';

/**
 * Resolve a saved active-list id to the concrete `searchTags` to apply.
 * - `null` (no keyword filter) -> `undefined`
 * - any id (including the built-in "builtin-swe") -> the matching list's tags
 *   from the server-provided `lists`, or `undefined` if it no longer exists.
 *
 * The built-in list is resolved from `lists` (the backend includes it) rather
 * than a local constant, so the resolved tags can never drift from what the
 * keyword-list UI compares the active selection against. Shared by
 * `useHydrateSavedFilters` (initial hydration) and the Saved Filters page
 * (push-on-save propagation) so both resolve identically.
 */
export function resolveActiveTags(
  activeId: string | null,
  lists: KeywordList[]
): SearchTag[] | undefined {
  if (activeId === null) return undefined;
  const match = lists.find((l) => l.id === activeId);
  return match ? match.tags.map((tag) => ({ ...tag })) : undefined;
}
