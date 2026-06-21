import type { KeywordList, SearchTag } from '../../types';

/**
 * A keyword list in the Preferences page draft. Identical to `KeywordList` plus
 * an `isNew` flag: locally-created lists carry a temporary client id (e.g.
 * `temp-1`) and must be POSTed (not PATCHed) on save.
 */
export interface DraftKeywordList extends KeywordList {
  isNew: boolean;
}

/** Prefix for client-generated temporary ids on not-yet-saved lists. */
export const TEMP_ID_PREFIX = 'temp-';

export function isTempId(id: string): boolean {
  return id.startsWith(TEMP_ID_PREFIX);
}

// ── tag mutators (operate on a list's `tags` field, mirroring the filter
//    reducer utils which target `searchTags`). Mutate the passed array in place
//    so they compose with the immutable copy made in the page's `mutateList`. ──

/** Add a tag (trim + de-dupe by text), mirroring `addSearchTagToFilters`. */
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

/** Build the editable draft from the server lists (preserves builtin-last order). */
export function toDraftLists(lists: KeywordList[]): DraftKeywordList[] {
  return [...lists]
    .sort((a, b) => {
      if (a.isBuiltin !== b.isBuiltin) return a.isBuiltin ? 1 : -1;
      return a.position - b.position;
    })
    .map((l) => ({ ...l, tags: l.tags.map((t) => ({ ...t })), isNew: false }));
}

/** Canonical (order-insensitive) string for a tag list, for dirty comparison. */
function canonicalTags(tags: SearchTag[]): string {
  return [...tags]
    .map((t) => `${t.text}:${t.mode}`)
    .sort()
    .join('|');
}

/**
 * Canonical signature of one list's saveable content (name + tags). Excludes
 * `position` and `id` so reordering/identity churn doesn't show as dirty here;
 * the page tracks structural identity (creates/deletes) separately.
 */
function canonicalList(list: { name: string; tags: SearchTag[] }): string {
  return `${list.name.trim()}::${canonicalTags(list.tags)}`;
}

/**
 * Canonical signature of the whole user-list set (built-in excluded — it is
 * read-only and never sent). Keyed by id so a create/delete flips the signature.
 */
export function canonicalListSet(lists: DraftKeywordList[]): string {
  return lists
    .filter((l) => !l.isBuiltin)
    .map((l) => `${l.isNew ? 'new' : l.id}=>${canonicalList(l)}`)
    .sort()
    .join('||');
}

export interface KeywordListDiff {
  toCreate: DraftKeywordList[];
  toUpdate: DraftKeywordList[];
  toDeleteIds: string[];
}

/**
 * Compute the create / update / delete sets needed to reconcile the server
 * lists with the draft. Built-in lists are never created, updated, or deleted.
 */
export function diffKeywordLists(
  serverLists: KeywordList[],
  draftLists: DraftKeywordList[]
): KeywordListDiff {
  const serverUser = serverLists.filter((l) => !l.isBuiltin);
  const draftUser = draftLists.filter((l) => !l.isBuiltin);

  const draftIds = new Set(draftUser.filter((l) => !l.isNew).map((l) => l.id));
  const serverById = new Map(serverUser.map((l) => [l.id, l]));

  const toCreate = draftUser.filter((l) => l.isNew);
  const toDeleteIds = serverUser.filter((l) => !draftIds.has(l.id)).map((l) => l.id);
  const toUpdate = draftUser.filter((l) => {
    if (l.isNew) return false;
    const server = serverById.get(l.id);
    if (!server) return false;
    return canonicalList(l) !== canonicalList(server);
  });

  return { toCreate, toUpdate, toDeleteIds };
}
