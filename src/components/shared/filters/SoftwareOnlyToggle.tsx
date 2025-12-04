import { FormControlLabel, Switch } from '@mui/material';

export interface SoftwareOnlyToggleProps {
  checked: boolean;
  onChange: () => void;
  label?: string;
}

/**
 * Toggle switch for filtering software engineering roles
 * When enabled, adds predefined search tags for software engineering positions
 */
export function SoftwareOnlyToggle({
  checked,
  onChange,
  label = 'Software engineering roles only',
}: SoftwareOnlyToggleProps) {
  return (
    <FormControlLabel control={<Switch checked={checked} onChange={onChange} />} label={label} />
  );
}
