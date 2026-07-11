import { useId } from 'react';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Checkbox,
  ListItemText,
  OutlinedInput,
  Tooltip,
} from '@mui/material';
import type { FacetOption } from '../../../types';

export interface FacetMultiSelectProps {
  label: string;
  options: FacetOption[];
  /** Selected slugs; empty/undefined renders as "All". */
  value: string[] | undefined;
  /** Emits the full new selection (empty array = All). */
  onChange: (slugs: string[]) => void;
  /** Optional hover hint on the whole control (e.g. the entry⊇new-grad note). */
  tooltip?: string;
  size?: 'small' | 'medium';
}

/**
 * Multi-select checkbox dropdown for an enrichment facet (Category / Level),
 * fed by the data-driven options from GET /api/jobs/facets. Sibling to the
 * single-select `FacetSelect` (still used by the admin correction UI, where a
 * job has exactly one category/level).
 *
 * OR logic within a facet; an empty selection means "All". The closed field
 * shows the selected labels joined (or "All" when empty) via `renderValue`.
 * `displayEmpty` + a forced-shrink InputLabel keep the floating label above
 * the "All" placeholder. The InputLabel and Select share a generated labelId so
 * the combobox exposes its accessible name for tests
 * (`getByRole('combobox', { name: label })`), mirroring FacetSelect.
 */
export function FacetMultiSelect({
  label,
  options,
  value,
  onChange,
  tooltip,
  size = 'small',
}: FacetMultiSelectProps) {
  const labelId = useId();
  const selected = value ?? [];
  const labelBySlug = new Map(options.map((opt) => [opt.slug, opt.label]));

  const control = (
    <FormControl size={size} sx={{ minWidth: 170 }}>
      <InputLabel id={labelId} shrink>
        {label}
      </InputLabel>
      <Select
        labelId={labelId}
        multiple
        displayEmpty
        value={selected}
        input={<OutlinedInput notched label={label} />}
        onChange={(e) => {
          const next = e.target.value;
          // MUI can hand back a comma-joined string on native events; normalize.
          onChange(typeof next === 'string' ? next.split(',') : next);
        }}
        renderValue={(sel) =>
          sel.length === 0 ? 'All' : sel.map((slug) => labelBySlug.get(slug) ?? slug).join(', ')
        }
      >
        {options.map((opt) => (
          <MenuItem key={opt.slug} value={opt.slug}>
            <Checkbox checked={selected.includes(opt.slug)} size="small" />
            <ListItemText primary={opt.label} />
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
