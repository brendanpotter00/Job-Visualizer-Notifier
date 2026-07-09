import { useId } from 'react';
import { FormControl, InputLabel, Select, MenuItem, Tooltip } from '@mui/material';
import type { FacetOption } from '../../../types';

export interface FacetSelectProps {
  label: string;
  options: FacetOption[];
  /** Selected slug; undefined renders the "All" option. */
  value: string | undefined;
  /** undefined = cleared ("All"). */
  onChange: (slug: string | undefined) => void;
  /** Optional hover hint on the whole control (e.g. the entry⊇new-grad note). */
  tooltip?: string;
  size?: 'small' | 'medium';
}

/**
 * Single-select dropdown for an enrichment facet (Category / Level), fed by
 * the data-driven options from GET /api/jobs/facets. Mirrors TimeWindowSelect:
 * the InputLabel and Select share a generated labelId so the combobox exposes
 * its accessible name for tests (`getByRole('combobox', { name: label })`).
 *
 * The cleared state is the empty string in the Select (MUI needs a concrete
 * value) but travels as `undefined` through the filter slices.
 */
export function FacetSelect({
  label,
  options,
  value,
  onChange,
  tooltip,
  size = 'small',
}: FacetSelectProps) {
  const labelId = useId();
  const control = (
    <FormControl size={size} sx={{ minWidth: 170 }}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        value={value ?? ''}
        label={label}
        onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)}
      >
        <MenuItem value="">
          <em>All</em>
        </MenuItem>
        {options.map((opt) => (
          <MenuItem key={opt.slug} value={opt.slug}>
            {opt.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
  return tooltip ? (
    <Tooltip title={tooltip} placement="top" enterDelay={400}>
      {control}
    </Tooltip>
  ) : (
    control
  );
}
