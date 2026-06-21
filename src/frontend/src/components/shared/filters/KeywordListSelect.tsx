import { useId, useMemo } from 'react';
import { FormControl, InputLabel, Select, MenuItem } from '@mui/material';
import { useGetKeywordListsQuery } from '../../../features/preferences/preferencesApi';
import { useAuth } from '../../../features/auth/useAuth';
import type { KeywordList, SearchTag } from '../../../types';

/** Sentinel values for the two synthetic, non-list options. */
const NONE_VALUE = '__none__';
const CUSTOM_VALUE = '__custom__';

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
  // viewers (the filter pages are public). They still get None / Custom and any
  // hand-added tags read as "Custom".
  const { isAuthenticated } = useAuth();
  const { data: lists } = useGetKeywordListsQuery(undefined, { skip: !isAuthenticated });

  const ordered = useMemo(() => orderLists(lists ?? []), [lists]);

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
      </Select>
    </FormControl>
  );
}
