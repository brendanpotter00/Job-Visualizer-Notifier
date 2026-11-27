import type { MouseEvent } from 'react';
import { Box, Chip } from '@mui/material';
import CancelIcon from '@mui/icons-material/Cancel';

export interface FacetValueChip {
  /** The selected value: the chip's key and what `onDelete` is called with. */
  slug: string;
  label: string;
}

export interface FacetValueChipsProps {
  /** The selected values, in display order. */
  values: FacetValueChip[];
  /** Removes one value. The caller emits the new selection. */
  onDelete: (slug: string) => void;
}

/**
 * The closed field of a facet multi-select (`FacetMultiSelect`,
 * `FacetTreeMultiSelect`): one chip per selected value. The chips look like
 * the Location field's (`AsyncMultiSelectAutocomplete`): MUI's small default
 * chip with its cancel icon, 4px apart, the gap the Autocomplete leaves
 * between small chips. Every multi-select in a filter row reads the same.
 *
 * The chips render from the Select's `renderValue`, so they sit INSIDE its
 * combobox, and MUI opens the menu on a mousedown anywhere in there:
 *
 * - A click on a chip's body opens the menu, like a click anywhere else on the
 *   field.
 * - A click on a chip's delete icon removes that one value and does NOT open
 *   the menu. The icon stops its mousedown before the Select sees it, and
 *   prevents its default, so focus stays where it was (as when a Location chip
 *   is removed).
 * - The chips are not tab stops (`tabIndex={-1}`, like Location's). The
 *   combobox stays the field's one stop, and the keyboard way to remove a value
 *   is the menu.
 *
 * The chips wrap, so many selections make the field taller, not wider. A long
 * label truncates inside its chip (MUI caps a chip at 100% width).
 */
export function FacetValueChips({ values, onDelete }: FacetValueChipsProps) {
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
      {values.map(({ slug, label }) => (
        <Chip
          key={slug}
          label={label}
          size="small"
          tabIndex={-1}
          onDelete={() => onDelete(slug)}
          deleteIcon={<CancelIcon onMouseDown={keepMenuClosed} />}
        />
      ))}
    </Box>
  );
}

function keepMenuClosed(event: MouseEvent) {
  event.stopPropagation();
  event.preventDefault();
}
