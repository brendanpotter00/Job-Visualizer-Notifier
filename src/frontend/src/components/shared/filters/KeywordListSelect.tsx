import { useId, useMemo } from 'react';
import { FormControl, InputLabel, Select, MenuItem } from '@mui/material';
import LoginIcon from '@mui/icons-material/Login';
import { useGetKeywordListsQuery } from '../../../features/savedFilters/savedFiltersApi';
import { useAuth } from '../../../features/auth/useAuth';
import { SOFTWARE_ENGINEERING_TAGS } from '../../../constants/tags';
import type { KeywordList, SearchTag } from '../../../types';

/** Sentinel values for the synthetic, non-list options. */
const NONE_VALUE = '__none__';
const CUSTOM_VALUE = '__custom__';
const SIGN_IN_VALUE = '__signin__';

/**
 * Locally synthesized built-in "Software Engineering" list for anonymous
 * viewers, who never hit the auth-gated keyword-lists query. Its id and tags
 * mirror the backend's synthesized `builtin-swe` list, so a signed-out
 * selection resolves identically to the server's once the user signs in.
 */
const ANON_BUILTIN_SWE_LIST: KeywordList = {
  id: 'builtin-swe',
  name: 'Software Engineering',
  tags: SOFTWARE_ENGINEERING_TAGS.map((tag) => ({ ...tag })),
  isBuiltin: true,
  position: 0,
};

export interface KeywordListSelectProps {
  /** The slice's current search tags (drives which option reads as selected). */
  value: SearchTag[] | undefined;
  /**
   * Called when the user picks a list ("None" -> `undefined`, otherwise a fresh
   * copy of the chosen list's tags). The parent dispatches the slice's
   * `set{Name}SearchTags` so this component stays slice-agnostic and testable.
   */
  onChange: (tags: SearchTag[] | undefined) => void;
  label?: string;
  size?: 'small' | 'medium';
}

/** Order-insensitive equality of two search-tag sets (by text + mode). */
function tagsEqual(a: SearchTag[], b: SearchTag[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((ta) => b.some((tb) => tb.text === ta.text && tb.mode === ta.mode));
}

/**
 * Sort user lists by `position`, with the read-only built-in list forced last.
 * The backend already returns this order, but sorting locally keeps the
 * component correct regardless of response ordering.
 */
function orderLists(lists: KeywordList[]): KeywordList[] {
  return [...lists].sort((a, b) => {
    if (a.isBuiltin !== b.isBuiltin) return a.isBuiltin ? 1 : -1;
    return a.position - b.position;
  });
}

/**
 * Dropdown that selects ONE active keyword list for a filter page, replacing the
 * old "Software engineering roles only" toggle. Options render as: user lists
 * (by position), then "None" (clears keyword filtering), then a disabled
 * "Custom" (selected when the current tags match no list), then the built-in
 * "Software Engineering (default)" list LAST.
 */
export function KeywordListSelect({
  value,
  onChange,
  label = 'Keyword list',
  size = 'small',
}: KeywordListSelectProps) {
  const labelId = useId();
  // Keyword lists are a logged-in feature; skip the authed request for anonymous
  // viewers (the filter pages are public). They still get None / Custom, any
  // hand-added tags read as "Custom", and a locally synthesized built-in SWE
  // list so the one-click preset stays available to everyone.
  const { isAuthenticated, login } = useAuth();
  const { data: lists } = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  const ordered = useMemo(
    () => orderLists(isAuthenticated ? (lists ?? []) : [ANON_BUILTIN_SWE_LIST]),
    [lists, isAuthenticated]
  );

  const currentTags = useMemo(() => value ?? [], [value]);
  const hasTags = currentTags.length > 0;

  // Resolve the selected option: "None" when there are no tags, the matching
  // list when the tags equal one exactly, otherwise the disabled "Custom".
  const matchingList = useMemo(
    () => (hasTags ? ordered.find((l) => tagsEqual(l.tags, currentTags)) : undefined),
    [ordered, currentTags, hasTags]
  );
  const isCustom = hasTags && !matchingList;
  const selectedValue = !hasTags ? NONE_VALUE : (matchingList?.id ?? CUSTOM_VALUE);

  const userLists = ordered.filter((l) => !l.isBuiltin);
  const builtinList = ordered.find((l) => l.isBuiltin);

  const handleChange = (nextValue: string) => {
    if (nextValue === CUSTOM_VALUE) return; // disabled; not selectable
    if (nextValue === SIGN_IN_VALUE) {
      void login().catch((error) => {
        console.error('[KeywordListSelect] Login failed:', error);
      });
      return;
    }
    if (nextValue === NONE_VALUE) {
      onChange(undefined);
      return;
    }
    const list = ordered.find((l) => l.id === nextValue);
    if (list) onChange(list.tags.map((tag) => ({ ...tag })));
  };

  return (
    <FormControl size={size} sx={{ minWidth: 220 }}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        value={selectedValue}
        label={label}
        onChange={(e) => handleChange(e.target.value)}
      >
        {userLists.map((list) => (
          <MenuItem key={list.id} value={list.id}>
            {list.name}
          </MenuItem>
        ))}
        <MenuItem value={NONE_VALUE}>None</MenuItem>
        {/* Shown only while active so the dropdown reflects hand-edited tags
            that match no saved list. Disabled — it is a status, not a choice. */}
        {isCustom && (
          <MenuItem value={CUSTOM_VALUE} disabled>
            Custom
          </MenuItem>
        )}
        {builtinList && (
          <MenuItem key={builtinList.id} value={builtinList.id}>
            Software Engineering (default)
          </MenuItem>
        )}
        {/* Anonymous-only CTA. Routed through a sentinel so it triggers sign-in
            without ever becoming the selected list value. */}
        {!isAuthenticated && (
          <MenuItem
            value={SIGN_IN_VALUE}
            sx={{
              borderTop: 1,
              borderColor: 'divider',
              color: 'primary.main',
              fontSize: '0.8125rem',
              whiteSpace: 'normal',
              gap: 1,
            }}
          >
            <LoginIcon fontSize="small" />
            Sign in to create custom lists
          </MenuItem>
        )}
      </Select>
    </FormControl>
  );
}
