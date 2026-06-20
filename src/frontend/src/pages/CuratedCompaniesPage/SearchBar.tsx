import { InputAdornment, TextField } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
}

/** Controlled search input for the curated-companies grid (client-side filter). */
export function SearchBar({ value, onChange }: SearchBarProps) {
  return (
    <TextField
      fullWidth
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Search companies…"
      slotProps={{
        // aria-label must land on the native <input>, not the TextField root,
        // so assistive tech (and getByLabelText) target the editable element.
        htmlInput: { 'aria-label': 'Search companies' },
        input: {
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon />
            </InputAdornment>
          ),
        },
      }}
    />
  );
}
