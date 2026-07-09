import { useState } from 'react';
import { TextField, Autocomplete } from '@mui/material';
import { renderSearchTagChips, makeSearchTagEnterHandler } from './searchTagInputShared.tsx';
import type { SearchTag } from '../../../types';

export interface SearchTagsInputProps {
  value: SearchTag[];
  onAdd: (tag: SearchTag) => void;
  onRemove: (text: string) => void;
  onToggleMode: (text: string) => void;
  /** Override the input placeholder (defaults to the include/exclude hint). */
  placeholder?: string;
}

/**
 * Autocomplete input for search tags with include/exclude mode toggling
 * Supports prefix detection: '-' for exclude, '+' for include
 */
export function SearchTagsInput({
  value,
  onAdd,
  onRemove,
  onToggleMode,
  placeholder,
}: SearchTagsInputProps) {
  const [inputValue, setInputValue] = useState('');

  const handleKeyDown = makeSearchTagEnterHandler(inputValue, onAdd, () => setInputValue(''));

  const handleChange = (_: unknown, newValue: (string | SearchTag)[]) => {
    // Handle chip removal via the X button
    if (Array.isArray(newValue)) {
      const removedTags = value.filter(
        (tag) => !newValue.some((v) => (typeof v === 'string' ? v : v.text) === tag.text)
      );
      removedTags.forEach((tag) => onRemove(tag.text));
    }
  };

  return (
    <Autocomplete
      multiple
      freeSolo
      size="small"
      options={[]}
      value={value}
      inputValue={inputValue}
      onInputChange={(_, newValue) => setInputValue(newValue)}
      onChange={handleChange}
      getOptionLabel={(option) => (typeof option === 'string' ? option : option.text)}
      isOptionEqualToValue={(option, tagValue) =>
        (typeof option === 'string' ? option : option.text) ===
        (typeof tagValue === 'string' ? tagValue : tagValue.text)
      }
      renderValue={(currentValue, getItemProps) =>
        renderSearchTagChips(currentValue, getItemProps, onToggleMode)
      }
      renderInput={(params) => (
        <TextField
          {...params}
          placeholder={
            placeholder ??
            (value.length > 0
              ? 'Add another tag...'
              : 'Type to add search tags: -senior (exclude) or senior (include)...')
          }
        />
      )}
      onKeyDown={handleKeyDown}
    />
  );
}
