import type { KeywordList, SearchTag } from '../../types';

/**
 * A keyword list in the Saved Filters page draft. Identical to `KeywordList` plus
 * an `isNew` flag: locally-created lists carry a temporary client id (e.g.
 * `temp-1`) and must be POSTed (not PATCHed) on save. Each card now owns its
 * own save lifecycle (create/update/delete persist immediately), so the draft
 * type is only used to carry one card's in-progress edits.
 */
export interface DraftKeywordList extends KeywordList {
  isNew: boolean;
}

/** Prefix for client-generated temporary ids on not-yet-saved lists. */
export const TEMP_ID_PREFIX = 'temp-';

export function isTempId(id: string): boolean {
  return id.startsWith(TEMP_ID_PREFIX);
}

/** Deep-copy a draft list so edits never mutate the cached server object. */
export function cloneDraftList(list: DraftKeywordList): DraftKeywordList {
  return { ...list, tags: list.tags.map((t) => ({ ...t })) };
}

// ── tag mutators (operate on a list's `tags` field, mirroring the filter
//    reducer utils which target `searchTags`). Mutate the passed list in place
//    so they compose with the immutable copy made in the card's `mutateDraft`. ──

/**
 * Add a tag (trim + de-dupe by text), mirroring `addSearchTagToFilters`.
 *
 * The editor keys tags by `text` (one keyword per list; flip include/exclude via
 * `toggleTagModeInList`), matching the app-wide search-tag model of the shared
 * `SearchTagsInput`. This is intentionally stricter than the backend, which
 * accepts the same text in both modes - the UI simply never produces such a pair.
 * Re-adding an existing keyword is a no-op (toggle its mode instead).
 */
export function addTagToList(list: DraftKeywordList, tag: SearchTag): void {
  const text = tag.text.trim();
  if (!text) return;
  if (!list.tags.some((t) => t.text === text)) {
    list.tags.push({ text, mode: tag.mode });
  }
}

/** Remove a tag by text. */
export function removeTagFromList(list: DraftKeywordList, text: string): void {
  list.tags = list.tags.filter((t) => t.text !== text);
}

/** Toggle a tag's include/exclude mode. */
export function toggleTagModeInList(list: DraftKeywordList, text: string): void {
  const tag = list.tags.find((t) => t.text === text);
  if (tag) tag.mode = tag.mode === 'include' ? 'exclude' : 'include';
}

/** Sort the server lists into display order: user lists by position, builtin last. */
export function toDraftLists(lists: KeywordList[]): DraftKeywordList[] {
  return [...lists]
    .sort((a, b) => {
      if (a.isBuiltin !== b.isBuiltin) return a.isBuiltin ? 1 : -1;
      return a.position - b.position;
    })
    .map((l) => ({ ...l, tags: l.tags.map((t) => ({ ...t })), isNew: false }));
}
