import type React from 'react';
import { Chip } from '@mui/material';
import type { AutocompleteRenderValueGetItemProps } from '@mui/material';
import { Add as AddIcon, Remove as RemoveIcon } from '@mui/icons-material';
import { parseSearchTagInput } from '../../../features/filters/utils/filterUtils.ts';
import type { SearchTag } from '../../../types';

/**
 * Shared building blocks for the two search-tag inputs — the pure free-form
 * `SearchTagsInput` (QAPage, saved-filters editor) and the merged
 * `KeywordFilterInput` (the two filter pages). Kept in one place so the chip
 * rendering and the Enter-to-add parsing can't drift between them.
 */

/** Narrow an Autocomplete value item to a `SearchTag` (skip freeSolo strings and option objects). */
export function isSearchTag(item: unknown): item is SearchTag {
  return (
    typeof item === 'object' &&
    item !== null &&
    'text' in item &&
    'mode' in item &&
    !('kind' in item)
  );
}

/**
 * Render the selected search tags as colored chips (green = include with a `+`
 * icon, red = exclude with a `−` icon); clicking a chip toggles its mode. Used
 * as the Autocomplete `renderValue`. Non-tag items (freeSolo strings, keyword-
 * list option objects) are skipped — they never become chips.
 */
export function renderSearchTagChips(
  value: readonly unknown[],
  getItemProps: AutocompleteRenderValueGetItemProps<true>,
  onToggleMode: (text: string) => void
) {
  return value.map((tag, index) => {
    if (!isSearchTag(tag)) return null;
    const { key, ...itemProps } = getItemProps({ index });
    return (
      <Chip
        key={key}
        color={tag.mode === 'include' ? 'success' : 'error'}
        icon={tag.mode === 'include' ? <AddIcon /> : <RemoveIcon />}
        label={tag.text}
        size="small"
        onClick={() => onToggleMode(tag.text)}
        {...itemProps}
      />
    );
  });
}

/**
 * Build the Enter-key handler that parses the typed text (`-`/`+` prefix →
 * exclude/include) and adds it as a tag.
 */
export function makeSearchTagEnterHandler(
  inputValue: string,
  onAdd: (tag: SearchTag) => void,
  clearInput: () => void
) {
  return (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && inputValue.trim()) {
      event.preventDefault();
      const parsed = parseSearchTagInput(inputValue);
      if (parsed) {
        onAdd(parsed);
        clearInput();
      }
    }
  };
}
