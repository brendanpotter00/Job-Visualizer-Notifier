import { useId } from 'react';
import { FormControl, InputLabel, Select, MenuItem } from '@mui/material';
import { TIME_WINDOWS } from '../../../constants/filters.ts';
import type { TimeWindow } from '../../../types';

export interface TimeWindowSelectProps {
  value: TimeWindow;
  onChange: (timeWindow: TimeWindow) => void;
  label?: string;
  size?: 'small' | 'medium';
}

/**
 * Dropdown selector for time window filter.
 *
 * The `InputLabel` and `Select` share a stable, generated `labelId` so the
 * combobox exposes its accessible name — tests can find it via
 * `getByRole('combobox', { name: '<label>' })`.
 */
export function TimeWindowSelect({
  value,
  onChange,
  label = 'Time Window',
  size = 'small',
}: TimeWindowSelectProps) {
  const labelId = useId();
  return (
    <FormControl size={size} sx={{ minWidth: 150 }}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        value={value}
        label={label}
        onChange={(e) => onChange(e.target.value as TimeWindow)}
      >
        {TIME_WINDOWS.map((tw) => (
          <MenuItem key={tw.value} value={tw.value}>
            {tw.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
