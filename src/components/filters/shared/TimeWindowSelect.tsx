import { FormControl, InputLabel, Select, MenuItem } from '@mui/material';
import { TIME_WINDOWS } from '../../../config/filterConstants';
import type { TimeWindow } from '../../../types';

export interface TimeWindowSelectProps {
  value: TimeWindow;
  onChange: (timeWindow: TimeWindow) => void;
  label?: string;
  size?: 'small' | 'medium';
}

/**
 * Dropdown selector for time window filter
 */
export function TimeWindowSelect({
  value,
  onChange,
  label = 'Time Window',
  size = 'small',
}: TimeWindowSelectProps) {
  return (
    <FormControl size={size} sx={{ minWidth: 150 }}>
      <InputLabel>{label}</InputLabel>
      <Select value={value} label={label} onChange={(e) => onChange(e.target.value as TimeWindow)}>
        {TIME_WINDOWS.map((tw) => (
          <MenuItem key={tw.value} value={tw.value}>
            {tw.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
