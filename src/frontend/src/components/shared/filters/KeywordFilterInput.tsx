import { useMemo, useRef, useState } from 'react';
import { TextField, Autocomplete, Box } from '@mui/material';
import type { AutocompleteChangeDetails, AutocompleteChangeReason } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import LoginIcon from '@mui/icons-material/Login';
import { useGetKeywordListsQuery } from '../../../features/savedFilters/savedFiltersApi';
import { useAuth } from '../../../features/auth/useAuth';
import {
  MAX_SEARCH_TAGS_REACHED_HELPER_TEXT,
  SOFTWARE_ENGINEERING_TAGS,
  canAddSearchTag,
  keywordListDoesNotFitHelperText,
  roomForSearchTags,
} from '../../../constants/tags';
import { extractErrorMessage } from '../../../lib/errors.ts';
import {
  isSearchTag,
  renderSearchTagChips,
  makeSearchTagEnterHandler,
} from './searchTagInputShared.tsx';
import type { KeywordList, SearchTag } from '../../../types';

/** Sentinel ids for the synthetic, non-list options. */
const NONE_ID = '__none__';
const SIGN_IN_ID = '__signin__';

/**
 * Locally synthesized built-in "Software Engineering" list for anonymous
 * viewers, who never hit the auth-gated keyword-lists query. Mirrors the
 * backend's synthesized `builtin-swe` list so a signed-out selection resolves
 * identically once the user signs in.
 */
const ANON_BUILTIN_SWE_LIST: KeywordList = {
  id: 'builtin-swe',
  name: 'Software Engineering',
  tags: SOFTWARE_ENGINEERING_TAGS.map((tag) => ({ ...tag })),
  isBuiltin: true,
  position: 0,
};

/** Discriminated option model for the single Autocomplete's dropdown rows. */
type KeywordOption =
  | { kind: 'list'; id: string; label: string; tags: SearchTag[]; isActive: boolean }
  | { kind: 'none'; id: typeof NONE_ID; label: string }
  | { kind: 'signin'; id: typeof SIGN_IN_ID; label: string };

export interface KeywordFilterInputProps {
  /** The slice's current search tags (chips). */
  value: SearchTag[] | undefined;
  /** Add one tag (typing) or, when a list is picked, one call per list tag (merge). */
  onAdd: (tag: SearchTag) => void;
  onRemove: (text: string) => void;
  onToggleMode: (text: string) => void;
  /** Clear all tags — the "None" option and the input's clear (X) button. */
  onClear: () => void;
}

/** Order-insensitive equality of two search-tag sets (by text + mode). */
function tagsEqual(a: SearchTag[], b: SearchTag[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((ta) => b.some((tb) => tb.text === ta.text && tb.mode === ta.mode));
}

/**
 * The chip set a refusal was measured against, as text + mode in order.
 *
 * A `listRejection` is a sentence about a specific set of chips ("only 2 of 20
 * slots are free"). The moment that set changes the sentence is about a state
 * that no longer exists, and the most visible way it changes is from OUTSIDE
 * this component: `RecentJobsFilters.tsx` renders Reset Filters and dispatches
 * `resetRecentJobsFilters` itself, so `value` empties without any handler here
 * running — leaving "remove some keywords" on screen above zero chips. Mode is
 * in the signature too, because clicking a chip to flip include/exclude goes
 * through `onToggleMode` and likewise never reaches `handleChange`.
 */
function tagSetSignature(tags: SearchTag[]): string {
  return tags.map((tag) => `${tag.mode}:${tag.text}`).join('\u0000');
}

/** Sort user lists by `position`, with the read-only built-in list forced last. */
function orderLists(lists: KeywordList[]): KeywordList[] {
  return [...lists].sort((a, b) => {
    if (a.isBuiltin !== b.isBuiltin) return a.isBuiltin ? 1 : -1;
    return a.position - b.position;
  });
}

/**
 * One control that merges the old free-form `SearchTagsInput` and the old
 * `KeywordListSelect` dropdown: a single MUI Autocomplete whose OPTIONS are the
 * keyword lists (plus "None" and, when signed out, a "Sign in" CTA) and whose
 * VALUE is the search-tag chips. Users can pick a list AND type free-form
 * keywords in the same control.
 *
 * Picking a list MERGES its tags onto whatever is already there (one `onAdd`
 * per tag). Dedupe is by text only (see `addSearchTagToFilters`), so on a
 * text collision the existing tag's mode wins (first-writer-wins) and the
 * list's copy is skipped — an intentional, minimal behavior.
 *
 * The merge is ALL-OR-NOTHING against `MAX_SEARCH_TAGS`. Dispatching the adds
 * one at a time and letting each one meet the cap independently means a list
 * that does not fit is applied in PART: with 18 chips already up, the 6-tag
 * built-in list contributes 2 keywords and drops 4, with nothing on screen
 * saying so — and since the option's checkmark only lights on an exact set
 * match, the reader has no way to tell the list is not the filter running. So
 * the fit is measured first, and a list that does not fit is refused whole with
 * the reason in `helperText`.
 */
export function KeywordFilterInput({
  value,
  onAdd,
  onRemove,
  onToggleMode,
  onClear,
}: KeywordFilterInputProps) {
  const [inputValue, setInputValue] = useState('');
  // Tracks the currently highlighted listbox option so a typed keyword + Enter
  // never accidentally applies a keyword list — it defers to MUI's selectOption
  // only when a row is actually highlighted. Reset whenever the input text
  // changes or the popup closes (see onInputChange/onClose), so a stale
  // mouse-hover highlight left over from a prior list pick can't outlive its
  // popup and silently swallow the next typed Enter.
  const highlightedRef = useRef<KeywordOption | null>(null);

  const { isAuthenticated, login } = useAuth();
  const {
    data: lists,
    isError: isListsError,
    error: listsError,
  } = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  // No toast/snackbar infra in the repo, so both failure modes — a failed
  // keyword-lists fetch and a failed sign-in redirect — surface inline through
  // the TextField error/helperText channel (mirrors AsyncMultiSelectAutocomplete).
  const [loginError, setLoginError] = useState<string | null>(null);
  // Set only when a picked list is refused for not fitting the budget, and
  // stamped with the chip set it was measured against so it cannot outlive it
  // (see `tagSetSignature`). `handleChange` / `onInputChange` still clear it
  // eagerly for the interactions that do not change `value` at all.
  const [listRejection, setListRejection] = useState<{
    message: string;
    tagSignature: string;
  } | null>(null);
  const listsErrorMessage = isListsError
    ? extractErrorMessage(listsError, 'Failed to load keyword lists')
    : null;
  const errorMessage = listsErrorMessage ?? loginError;

  const currentTags = useMemo(() => value ?? [], [value]);
  const hasTags = currentTags.length > 0;
  // `addSearchTagToFilters` silently REFUSES the add past this point (it is the
  // search endpoint's combined include+exclude budget — see MAX_SEARCH_TAGS). A
  // refusal with nothing on screen is indistinguishable from a broken input, so
  // the reason has to be visible before the reader tries. Asked of the shared
  // reader rather than re-derived, so this line and the reducer that actually
  // refuses cannot disagree about where the boundary is.
  const atTagLimit = !canAddSearchTag(currentTags);
  const tagSignature = useMemo(() => tagSetSignature(currentTags), [currentTags]);
  // Derived, not stored: a refusal renders only while the chips it describes are
  // still the chips on screen.
  const listRejectionMessage =
    listRejection !== null && listRejection.tagSignature === tagSignature
      ? listRejection.message
      : null;

  const options = useMemo<KeywordOption[]>(() => {
    const ordered = orderLists(isAuthenticated ? (lists ?? []) : [ANON_BUILTIN_SWE_LIST]);
    const userLists = ordered.filter((l) => !l.isBuiltin);
    const builtin = ordered.find((l) => l.isBuiltin);

    const toListOption = (l: KeywordList): KeywordOption => ({
      kind: 'list',
      id: l.id,
      label: l.isBuiltin ? 'Software Engineering (default)' : l.name,
      tags: l.tags,
      isActive: hasTags && tagsEqual(l.tags, currentTags),
    });

    return [
      ...userLists.map(toListOption),
      { kind: 'none', id: NONE_ID, label: 'None' },
      ...(builtin ? [toListOption(builtin)] : []),
      ...(!isAuthenticated
        ? [{ kind: 'signin', id: SIGN_IN_ID, label: 'Sign in to create custom lists' } as const]
        : []),
    ];
  }, [isAuthenticated, lists, currentTags, hasTags]);

  const addTypedTag = makeSearchTagEnterHandler(inputValue, onAdd, () => setInputValue(''));

  const handleKeyDown = (event: React.KeyboardEvent) => {
    // If a listbox option is highlighted, let MUI's selectOption handle Enter so
    // a typed keyword + Enter never accidentally applies a keyword list.
    if (event.key === 'Enter' && highlightedRef.current != null) return;
    addTypedTag(event);
  };

  /**
   * Apply a whole keyword list, or none of it.
   *
   * `addSearchTagToFilters` trims, skips blanks and dedupes by TEXT, so the real
   * cost of a list is only the tags it would actually add — a list whose every
   * tag is already a chip costs nothing and is always allowed through. When that
   * cost exceeds the remaining room, not one `onAdd` is dispatched.
   *
   * "Costs nothing is always allowed" holds in BOTH regimes, and the second one
   * is why `room` comes from `roomForSearchTags` instead of a bare subtraction.
   * At or under the cap the two are identical. OVER it — reachable, because
   * `hydrate{Name}Filters` `Object.assign`s a legacy oversized saved list
   * straight into `filters.searchTags` — a bare subtraction is negative, and
   * `0 > -5` refuses the free re-pick with "needs 0 more keywords and only 0 of
   * 20 slots are free". The floor makes the zero-cost case fall through to the
   * (empty) dispatch loop, exactly as it does under the cap.
   */
  const applyList = (opt: Extract<KeywordOption, { kind: 'list' }>) => {
    const seen = new Set(currentTags.map((tag) => tag.text));
    const additions: SearchTag[] = [];
    for (const tag of opt.tags) {
      const text = tag.text.trim();
      if (!text || seen.has(text)) continue;
      seen.add(text);
      additions.push({ text, mode: tag.mode });
    }

    const room = roomForSearchTags(currentTags);
    if (additions.length > room) {
      setListRejection({
        message: keywordListDoesNotFitHelperText(additions.length, room),
        tagSignature,
      });
      return;
    }
    additions.forEach((tag) => onAdd(tag));
  };

  const handleChange = (
    _event: React.SyntheticEvent,
    _newValue: unknown,
    reason: AutocompleteChangeReason,
    details?: AutocompleteChangeDetails<KeywordOption | SearchTag | string>
  ) => {
    // Any new interaction supersedes a previous list refusal; the branches below
    // re-set it if this pick is refused too.
    setListRejection(null);
    // `value` is controlled from Redux; never feed `_newValue` back — it would
    // inject a keyword-list option object as a broken chip. Branch on reason.
    if (reason === 'clear') {
      onClear();
      return;
    }
    if (reason === 'removeOption') {
      const removed = details?.option;
      if (isSearchTag(removed)) onRemove(removed.text);
      return;
    }
    if (reason === 'selectOption') {
      const opt = details?.option;
      if (!opt || typeof opt === 'string' || !('kind' in opt)) return;
      if (opt.kind === 'none') {
        onClear();
      } else if (opt.kind === 'signin') {
        setLoginError(null);
        void login().catch((error) => {
          setLoginError(extractErrorMessage(error, 'Sign-in failed. Please try again.'));
        });
      } else {
        applyList(opt);
      }
    }
    // `createOption` (freeSolo Enter) is handled by handleKeyDown; ignore here.
  };

  return (
    <Autocomplete<KeywordOption | SearchTag, true, false, true>
      multiple
      freeSolo
      // freeSolo hides the popup indicator by default; force it so the arrow
      // signals that pickable keyword lists live behind this input.
      forcePopupIcon
      autoHighlight={false}
      size="small"
      // The clear (X) + popup (▼) buttons are absolutely positioned with a
      // `translateY(-50%)` centering transform, so `top` sets their *center*,
      // not their edge — half the single-row input's min-height (RESPONSIVE
      // .control.minHeight / the theme's 44px floor) lands them dead-center
      // on one row. When chips wrap to multiple rows, that same fixed value
      // keeps them pinned to the first row instead of drifting to the middle
      // of the taller box (which would overlap wrapped chips).
      sx={{ '& .MuiAutocomplete-endAdornment': { top: { xs: 18, sm: 22 } } }}
      options={options}
      value={value ?? []}
      inputValue={inputValue}
      onInputChange={(_, next) => {
        setInputValue(next);
        setListRejection(null);
        // Typing new text invalidates any prior highlight (including a stale
        // mouse-hover highlight from an earlier list pick), so a typed keyword +
        // Enter is never silently deferred to MUI's selectOption and dropped.
        highlightedRef.current = null;
      }}
      onChange={handleChange}
      onClose={() => {
        // A highlight cannot outlive its popup: reset so a hover-set highlight
        // from a just-closed popup can't hijack the next typed Enter.
        highlightedRef.current = null;
      }}
      onHighlightChange={(_, option) => {
        highlightedRef.current =
          option && typeof option !== 'string' && 'kind' in option ? option : null;
      }}
      filterOptions={(x) => x}
      getOptionLabel={(option) => {
        if (typeof option === 'string') return option;
        if ('kind' in option) return option.label;
        return option.text;
      }}
      // Options (keyword lists) and values (search tags) are different shapes and
      // never "equal" — nothing in the listbox reads as selected.
      isOptionEqualToValue={() => false}
      renderValue={(currentValue, getItemProps) =>
        renderSearchTagChips(currentValue, getItemProps, onToggleMode)
      }
      renderOption={(props, option) => {
        const { key, ...optionProps } = props;
        if (typeof option === 'string' || !('kind' in option)) return null;
        if (option.kind === 'signin') {
          return (
            <Box
              component="li"
              key={key}
              {...optionProps}
              sx={{ color: 'primary.main', fontSize: '0.8125rem', gap: 1 }}
            >
              <LoginIcon fontSize="small" />
              {option.label}
            </Box>
          );
        }
        return (
          <Box
            component="li"
            key={key}
            {...optionProps}
            sx={{ display: 'flex', justifyContent: 'space-between', gap: 1 }}
          >
            {option.label}
            {option.kind === 'list' && option.isActive && (
              <CheckIcon fontSize="small" color="primary" />
            )}
          </Box>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label="Keywords"
          placeholder={
            hasTags
              ? 'Add a keyword or pick a list…'
              : 'Pick a list or type a keyword (- to exclude)…'
          }
          error={errorMessage != null}
          // A real failure outranks both budget lines; the cap is a rule, not an
          // error. A refused list outranks the standing cap notice because it
          // explains something the reader just DID, not a standing condition —
          // and at 18-of-20 chips the standing notice is not even showing.
          helperText={
            errorMessage ??
            listRejectionMessage ??
            (atTagLimit ? MAX_SEARCH_TAGS_REACHED_HELPER_TEXT : undefined)
          }
        />
      )}
      onKeyDown={handleKeyDown}
    />
  );
}
