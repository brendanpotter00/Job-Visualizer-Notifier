import Autocomplete from '@mui/material/Autocomplete';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import TextField from '@mui/material/TextField';
import type { FacetOption } from '../../../types';

export const MAX_SUBCATEGORIES = 2;

interface SubcategoryOrderedSelectProps {
  /** LIVE facet options. Never a fallback constant — see the note below. */
  options: FacetOption[];
  /** ORDERED: index 0 is the primary specialty. */
  value: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}

/**
 * An ORDERED, max-2 subcategory picker.
 *
 * ⚠ THE ORDER IS THE PRODUCT, not a detail. Index 0 is the PRIMARY specialty —
 * it is what the job card shows first and what the eval scores primary accuracy
 * against. MUI's `Autocomplete multiple` appends each selection in CLICK order
 * (verified on the installed 7.3.6), and that behaviour is the entire mechanism
 * behind "primary first". It is undocumented, so it is pinned by a test rather
 * than by trust: ticking Frontend then Backend must emit
 * `['frontend', 'backend']`, NOT the alphabetical `['backend', 'frontend']`.
 *
 * ⚠ OPTIONS COME FROM LIVE FACETS, NEVER FROM A FALLBACK CONSTANT. An admin
 * writing a human label — the scarcest and most valuable data in this whole
 * system — must not be offered a slug the database will reject, and must not be
 * denied one the database has. The caller passes `facets?.subcategories ?? []`;
 * an empty list correctly renders a control with nothing to pick.
 *
 * ⚠ CLEARING ON A CATEGORY CHANGE HAPPENS IN THE CALLER'S HANDLER, never in an
 * effect here. This component is controlled and has no opinion about the
 * category; a `useEffect` that reset its own value would be exactly the
 * setState-in-effect pattern the file's lint rules forbid, and it would fight
 * the parent for ownership of the value.
 *
 * `node_modules` is hoisted to the REPO ROOT (`/Job-Visualizer-Notifier/node_modules/@mui/material`);
 * `src/frontend/node_modules` holds only Vite caches.
 */
export function SubcategoryOrderedSelect({
  options,
  value,
  onChange,
  disabled = false,
}: SubcategoryOrderedSelectProps) {
  const bySlug = new Map(options.map((option) => [option.slug, option]));
  const labelFor = (slug: string) => bySlug.get(slug)?.label ?? slug;
  const atLimit = value.length >= MAX_SUBCATEGORIES;

  return (
    <Autocomplete
      multiple
      disableCloseOnSelect
      disabled={disabled}
      options={options.map((option) => option.slug)}
      value={value}
      // MUI hands back the selection in CLICK order; pass it straight through.
      // Any sort() here would silently destroy the primary-first contract.
      onChange={(_event, next) => onChange(next.slice(0, MAX_SUBCATEGORIES))}
      getOptionLabel={labelFor}
      // Once two are chosen, every UNSELECTED option is disabled — the limit is
      // shown rather than enforced by silently dropping a third click.
      getOptionDisabled={(slug) => atLimit && !value.includes(slug)}
      renderOption={(props, slug, { selected }) => {
        const { key, ...rest } = props as { key?: string } & Record<string, unknown>;
        return (
          <li key={key ?? slug} {...rest}>
            <Checkbox
              size="small"
              checked={selected}
              disabled={atLimit && !selected}
              sx={{ mr: 1 }}
            />
            {labelFor(slug)}
          </li>
        );
      }}
      renderValue={(selected, getItemProps) =>
        selected.map((slug, index) => (
          <Chip
            size="small"
            // Filled = primary, outlined = secondary, so the ORDER is legible
            // at a glance instead of being invisible state.
            variant={index === 0 ? 'filled' : 'outlined'}
            color={index === 0 ? 'primary' : 'default'}
            label={labelFor(slug)}
            {...getItemProps({ index })}
            key={slug}
          />
        ))
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label="Subcategories"
          placeholder={value.length ? '' : 'Primary first — max 2'}
          helperText="First chip is the primary specialty"
        />
      )}
      sx={{ mb: 2 }}
    />
  );
}
