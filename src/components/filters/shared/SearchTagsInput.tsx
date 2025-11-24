import { useState } from 'react';
import { TextField, Autocomplete, Chip } from '@mui/material';
import { Add as AddIcon, Remove as RemoveIcon } from '@mui/icons-material';
import { parseSearchTagInput } from '../../../utils/filterUtils';
import type { SearchTag } from '../../../types';

export interface SearchTagsInputProps {
  value: SearchTag[];
  onAdd: (tag: SearchTag) => void;
  onRemove: (text: string) => void;
  onToggleMode: (text: string) => void;
}

/**
 * Autocomplete input for search tags with include/exclude mode toggling
 * Supports prefix detection: '-' for exclude, '+' for include
 */
export function SearchTagsInput({ value, onAdd, onRemove, onToggleMode }: SearchTagsInputProps) {
  const [inputValue, setInputValue] = useState('');

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && inputValue.trim()) {
      event.preventDefault();

      const parsed = parseSearchTagInput(inputValue);
      if (parsed) {
        onAdd(parsed);
        setInputValue('');
      }
    }
  };

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
        currentValue.map((tag, index) => {
          if (typeof tag === 'string') return null;
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
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          placeholder={
            value.length > 0
              ? 'Add another tag...'
              : 'Type to add search tags: -senior (exclude) or senior (include)...'
          }
        />
      )}
      onKeyDown={handleKeyDown}
    />
  );
}
