import { useCallback } from 'react';
import { useAppDispatch } from '../../app/hooks';
import type { KeywordList, SavedFilters } from '../../types';
import {
  savedFiltersApi,
  useCreateKeywordListMutation,
  useUpdateKeywordListMutation,
  useUpdateSavedFiltersMutation,
} from '../savedFilters/savedFiltersApi';
import { defaultSearchGraphActions } from '../savedFilters/propagateSavedFilters';
import {
  DEFAULT_SEARCH_LIST_NAME,
  defaultSearchKey,
  planKeywordList,
  toSavedFiltersPayload,
  type DefaultSearch,
  type KeywordListPlan,
} from './defaultSearch';
import { saveFailed, saveStarted, saveSucceeded } from './defaultSearchSlice';

export const SAVE_DEFAULT_SEARCH_ERROR = "Couldn't save your default search. Try again.";
export const TOO_MANY_KEYWORD_LISTS_ERROR =
  'Too many keyword lists. Delete one in Saved Filters, then try again.';

/** What the save starts from: the saved row and keyword lists the caller has loaded. */
export interface SaveDefaultSearchContext {
  current: SavedFilters;
  lists: KeywordList[];
}

/** An error whose message is meant for the reader. */
class ReaderFacingError extends Error {}

function errorStatus(err: unknown): unknown {
  return err !== null && typeof err === 'object' && 'status' in err
    ? (err as { status: unknown }).status
    : undefined;
}

/** `lists` with `written` replacing its old copy, or added before the built-in. */
function withList(lists: KeywordList[], written: KeywordList): KeywordList[] {
  const index = lists.findIndex((list) => list.id === written.id);
  if (index >= 0) return lists.map((list) => (list.id === written.id ? written : list));
  const builtinAt = lists.findIndex((list) => list.isBuiltin);
  if (builtinAt < 0) return [...lists, written];
  return [...lists.slice(0, builtinAt), written, ...lists.slice(builtinAt)];
}

/**
 * Saves a default search: the Recent filters become the reader's saved filters.
 * The button and the after-sign-in flow both call `save`.
 *
 * 1. Point the keywords at a list (`planKeywordList`): reuse one that already
 *    matches, else PATCH or POST the "Default search" list. A POST 409 means the
 *    lists we hold are stale: refetch once and plan again.
 * 2. PUT the whole saved-filters row (`toSavedFiltersPayload`).
 * 3. Write the answers into both caches, so the button reads "unchanged" on the
 *    very next render, with no flicker while the invalidated queries refetch.
 * 4. Move the Companies page's shared filters (`defaultSearchGraphActions`).
 *
 * Not atomic: the list write and the PUT are two requests. A failed PUT after a
 * list write leaves the keywords saved and the rest unsaved; the error shows and
 * the invalidated caches refetch, so the button still tells the truth.
 */
export function useSaveDefaultSearch() {
  const dispatch = useAppDispatch();
  const [createKeywordList] = useCreateKeywordListMutation();
  const [updateKeywordList] = useUpdateKeywordListMutation();
  const [updateSavedFilters] = useUpdateSavedFiltersMutation();

  const save = useCallback(
    async (search: DefaultSearch, { current, lists }: SaveDefaultSearchContext) => {
      // A snapshot: an edit made during the save is not part of it, and keeps
      // the button enabled afterwards.
      const key = defaultSearchKey(search);
      dispatch(saveStarted());
      try {
        let known = lists;
        let written: KeywordList | null = null;
        const planFor = (from: KeywordList[]): KeywordListPlan =>
          planKeywordList(search.searchTags, current.recentActiveKeywordListId, from);
        let plan = planFor(known);

        if (plan.kind === 'create') {
          try {
            written = await createKeywordList({
              name: DEFAULT_SEARCH_LIST_NAME,
              tags: search.searchTags,
            }).unwrap();
          } catch (err) {
            const status = errorStatus(err);
            if (status === 422) throw new ReaderFacingError(TOO_MANY_KEYWORD_LISTS_ERROR);
            if (status !== 409) throw err;
            // A "Default search" list exists that our copy of the lists missed.
            known = await dispatch(
              savedFiltersApi.endpoints.getKeywordLists.initiate(undefined, {
                subscribe: false,
                forceRefetch: true,
              })
            ).unwrap();
            plan = planFor(known);
            if (plan.kind === 'create') throw err;
          }
        }
        if (plan.kind === 'update') {
          written = await updateKeywordList({ id: plan.id, tags: search.searchTags }).unwrap();
        }
        if (written) known = withList(known, written);

        const listId = written ? written.id : plan.kind === 'reuse' ? plan.id : null;
        const saved = await updateSavedFilters(
          toSavedFiltersPayload(search, current, listId)
        ).unwrap();

        await dispatch(savedFiltersApi.util.upsertQueryData('getSavedFilters', undefined, saved));
        if (written) {
          const list = written;
          dispatch(
            savedFiltersApi.util.updateQueryData('getKeywordLists', undefined, (draft) => {
              const index = draft.findIndex((l) => l.id === list.id);
              if (index >= 0) {
                draft[index] = list;
                return;
              }
              const builtinAt = draft.findIndex((l) => l.isBuiltin);
              if (builtinAt < 0) draft.push(list);
              else draft.splice(builtinAt, 0, list);
            })
          );
        }
        defaultSearchGraphActions(saved, known).forEach((action) => dispatch(action));
        dispatch(saveSucceeded(key));
        return true;
      } catch (err) {
        console.error('[useSaveDefaultSearch] save failed', err);
        const message =
          err instanceof ReaderFacingError ? err.message : SAVE_DEFAULT_SEARCH_ERROR;
        dispatch(saveFailed({ key, message }));
        return false;
      }
    },
    [dispatch, createKeywordList, updateKeywordList, updateSavedFilters]
  );

  return { save };
}
