import { FormControlLabel, Switch } from '@mui/material';

export interface SoftwareOnlyToggleProps {
  checked: boolean;
  onChange: () => void;
  label?: string;
}

/**
 * Toggle switch for filtering software-only roles
 */
export function SoftwareOnlyToggle({
  checked,
  onChange,
  label = 'Software roles only',
}: SoftwareOnlyToggleProps) {
  return (
    <FormControlLabel control={<Switch checked={checked} onChange={onChange} />} label={label} />
  );
}
