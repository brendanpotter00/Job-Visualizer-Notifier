import { useMemo, useRef, useState } from 'react';
import { TextField, Autocomplete, Box } from '@mui/material';
import type { AutocompleteChangeDetails, AutocompleteChangeReason } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import LoginIcon from '@mui/icons-material/Login';
import { useGetKeywordListsQuery } from '../../../features/savedFilters/savedFiltersApi';
import { useAuth } from '../../../features/auth/useAuth';
import { SOFTWARE_ENGINEERING_TAGS } from '../../../constants/tags';
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
  // never accidentally applies a keyword list (it defers to MUI's selectOption
  // only when a row is actually highlighted).
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
  const listsErrorMessage = isListsError
    ? extractErrorMessage(listsError, 'Failed to load keyword lists')
    : null;
  const errorMessage = listsErrorMessage ?? loginError;

  const currentTags = useMemo(() => value ?? [], [value]);
  const hasTags = currentTags.length > 0;

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

  const handleChange = (
    _event: React.SyntheticEvent,
    _newValue: unknown,
    reason: AutocompleteChangeReason,
    details?: AutocompleteChangeDetails<KeywordOption | SearchTag | string>
  ) => {
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
        // Merge: one add per tag, reusing the slice's dedupe-by-text.
        opt.tags.forEach((tag) => onAdd({ ...tag }));
      }
    }
    // `createOption` (freeSolo Enter) is handled by handleKeyDown; ignore here.
  };

  return (
    <Autocomplete<KeywordOption | SearchTag, true, false, true>
      multiple
      freeSolo
      autoHighlight={false}
      size="small"
      options={options}
      value={value ?? []}
      inputValue={inputValue}
      onInputChange={(_, next) => setInputValue(next)}
      onChange={handleChange}
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
          helperText={errorMessage ?? undefined}
        />
      )}
      onKeyDown={handleKeyDown}
    />
  );
}
