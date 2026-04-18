import { useMemo } from 'react';
import Autocomplete from '@mui/material/Autocomplete';
import TextField from '@mui/material/TextField';

export interface CompanyOption {
  id: string;
  name: string;
}

export interface CompanySearchAddInputProps {
  companies: CompanyOption[];
  selectedIds: Set<string>;
  inputValue: string;
  onInputChange: (value: string) => void;
  onAdd: (id: string) => void;
}

/**
 * Fast keyboard-driven search-and-add input for adding companies to the
 * selected set. Uses MUI Autocomplete with `autoHighlight` so pressing Enter
 * commits the top match. After commit, the input clears via controlled
 * `inputValue`. `value` is kept controlled as `null` to avoid MUI's
 * "non-existent option" warning when we filter the option list.
 */
export function CompanySearchAddInput({
  companies,
  selectedIds,
  inputValue,
  onInputChange,
  onAdd,
}: CompanySearchAddInputProps) {
  const availableOptions = useMemo(
    () => companies.filter((c) => !selectedIds.has(c.id)),
    [companies, selectedIds]
  );

  return (
    <Autocomplete<CompanyOption, false, false, false>
      options={availableOptions}
      value={null}
      inputValue={inputValue}
      onInputChange={(_, v) => onInputChange(v)}
      onChange={(_, option) => {
        if (option) {
          onAdd(option.id);
          onInputChange('');
        }
      }}
      getOptionLabel={(o) => o.name}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      autoHighlight
      blurOnSelect={false}
      clearOnBlur={false}
      noOptionsText="No companies match"
      renderInput={(params) => (
        <TextField
          {...params}
          label="Search companies"
          placeholder="Type a company name and press Enter"
        />
      )}
    />
  );
}
