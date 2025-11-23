import { Autocomplete, TextField, Chip } from '@mui/material';
import { getArrayDiff } from '../../../utils/filterUtils';

export interface MultiSelectAutocompleteProps {
  label: string;
  options: string[];
  value: string[];
  onAdd: (item: string) => void;
  onRemove: (item: string) => void;
  placeholder?: string;
  size?: 'small' | 'medium';
  minWidth?: number;
}

/**
 * Generic multi-select autocomplete component for string arrays
 * Used for locations, departments, and other multi-select filters
 */
export function MultiSelectAutocomplete({
  label,
  options,
  value,
  onAdd,
  onRemove,
  placeholder = `Select ${label.toLowerCase()}...`,
  size = 'small',
  minWidth = 200,
}: MultiSelectAutocompleteProps) {
  const handleChange = (_: unknown, newValue: string[]) => {
    if (Array.isArray(newValue)) {
      const { added, removed } = getArrayDiff(value, newValue);

      // Handle removals first
      removed.forEach((item) => onRemove(item));

      // Then handle additions
      added.forEach((item) => onAdd(item));
    }
  };

  return (
    <Autocomplete
      multiple
      size={size}
      options={options}
      value={value}
      onChange={handleChange}
      renderValue={(currentValue, getItemProps) =>
        currentValue.map((option, index) => {
          const { key, ...itemProps } = getItemProps({ index });
          return <Chip key={key} label={option} size="small" {...itemProps} />;
        })
      }
      renderInput={(params) => <TextField {...params} label={label} placeholder={placeholder} />}
      sx={{ minWidth }}
    />
  );
}
