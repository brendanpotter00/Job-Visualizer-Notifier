import { Autocomplete, TextField, Chip } from '@mui/material';
import { ROLE_CATEGORIES } from '../../../config/filterConstants';
import { getArrayDiff } from '../../../utils/filterUtils';
import type { SoftwareRoleCategory } from '../../../types';

export interface RoleCategorySelectProps {
  value: SoftwareRoleCategory[];
  onAdd: (category: SoftwareRoleCategory) => void;
  onRemove: (category: SoftwareRoleCategory) => void;
  size?: 'small' | 'medium';
  minWidth?: number;
}

/**
 * Multi-select autocomplete for software role categories
 */
export function RoleCategorySelect({
  value,
  onAdd,
  onRemove,
  size = 'small',
  minWidth = 200,
}: RoleCategorySelectProps) {
  const handleChange = (_: unknown, newValue: SoftwareRoleCategory[]) => {
    if (Array.isArray(newValue)) {
      const { added, removed } = getArrayDiff(value, newValue);

      // Handle removals first
      removed.forEach((cat) => onRemove(cat));

      // Then handle additions
      added.forEach((cat) => onAdd(cat));
    }
  };

  const getLabel = (category: SoftwareRoleCategory): string => {
    return ROLE_CATEGORIES.find((c) => c.value === category)?.label || category;
  };

  return (
    <Autocomplete
      multiple
      size={size}
      options={ROLE_CATEGORIES.map((cat) => cat.value)}
      value={value}
      onChange={handleChange}
      renderValue={(currentValue, getItemProps) =>
        currentValue.map((option, index) => {
          const { key, ...itemProps } = getItemProps({ index });
          return <Chip key={key} label={getLabel(option)} size="small" {...itemProps} />;
        })
      }
      getOptionLabel={(option) => getLabel(option)}
      renderInput={(params) => (
        <TextField {...params} label="Type (Experiemental)" placeholder="Select categories..." />
      )}
      sx={{ minWidth }}
    />
  );
}
