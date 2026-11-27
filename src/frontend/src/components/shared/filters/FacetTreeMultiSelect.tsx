import { useId } from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Checkbox,
  ListItemText,
  OutlinedInput,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { VISUALLY_HIDDEN_SX } from '../../../lib/visuallyHidden';
import type { FacetOption } from '../../../types';
import { FacetValueChips } from './FacetValueChips.tsx';

/**
 * Cap on the open menu's height.
 *
 * With every parent unticked the menu is just the six category rows, the same
 * as the flat `FacetMultiSelect`, which has no cap because six rows fit
 * anywhere (measured at 316px, 50px a row, on a phone and a laptop alike, so
 * neither cap is reached). The cap only matters once a parent is OPEN: ticking
 * Software Engineering adds its seventeen specialties, twenty-three rows and
 * about 1,170px in all, which overflows a phone viewport and most laptop ones.
 * The menu then scrolls inside this height instead.
 */
const MENU_MAX_HEIGHT = { xs: '60vh', sm: 400 };

export interface FacetTreeMultiSelectProps {
  label: string;
  /** Parent (category) options. */
  options: FacetOption[];
  /**
   * Child (subcategory) options, each carrying its `parentSlug`. An EMPTY array
   * makes this control render identically to the flat `FacetMultiSelect` — just
   * the parent rows — which is how the reveal flag turns the tree off.
   */
  childOptions: FacetOption[];
  /** Selected parent slugs; empty/undefined renders as "All". */
  value: string[] | undefined;
  /** Selected child slugs. */
  childValue: string[] | undefined;
  /**
   * Emits BOTH arrays on every change.
   *
   * One handler rather than two is load-bearing: the auto-check-parent rule and
   * the untick-clears-children rule both move the two selections together, and
   * two separate callbacks would let a consumer apply one and drop the other,
   * desyncing a child from its parent with no way to notice.
   */
  onChange: (next: { category: string[]; subcategory: string[] }) => void;
  size?: 'small' | 'medium';
}

/**
 * Two-level multi-select checkbox dropdown for the enrichment category facet
 * and its SWE subcategory children, fed by GET /api/jobs/facets.
 *
 * A SIBLING of `FacetMultiSelect`, deliberately not a mode on it.
 * `FacetMultiSelect` has six live instances across three consumers and three of
 * them are the Level control, which will never be hierarchical; a `childOptions`
 * branch there would put a tree's worth of state in front of all six.
 *
 * BEHAVIOUR
 * ---------
 * Tick to reveal: the same pattern as the onboarding Job Category question
 * (`components/onboarding/RoleQuestion.tsx`), kept inside the MUI Select menu.
 *
 * - A parent's children are rendered ONLY while that parent is ticked. With it
 *   unticked the menu shows just the parent rows. Ticking it shows its children
 *   as indented rows right under it, and opening the menu with it already
 *   ticked (from saved filters, say) shows them straight away. Today only
 *   Software Engineering has children, but nothing here is specific to it.
 * - Unticking a parent unticks it, CLEARS its ticked children and hides them,
 *   all in ONE emit. This replaced a rule where the first click only cleared
 *   the children and kept the parent ticked.
 * - A child AUTO-CHECKS its parent. The menu never offers a child under an
 *   unticked parent, so this is for stored data: a child saved without its
 *   parent gets the parent back on the next emit. A subcategory selection with
 *   no category selection would be filtered out server-side by the category
 *   predicate, so the two are only ever emitted together.
 * - A parent with children shows a chevron at the row's right edge that turns
 *   when the row is open, and a visually hidden ", N specialties" in its label
 *   so a screen reader hears what ticking it reveals. The parent's checkbox is
 *   indeterminate while it owns ticked children.
 * - Revealed children are plain MenuItems in the same list, so MUI's arrow-key
 *   navigation and Enter toggling reach them with no extra wiring.
 * - The closed field shows one chip per selected item (`FacetValueChips`, the
 *   Location field's look): each parent, then its own ticked children, each
 *   labelled by its own name. A chip's delete icon is the same edit as
 *   unticking that row: a parent's takes its children with it, a child's
 *   leaves the parent ticked.
 *
 * WHY THIS IS NOT THE OLD ACCORDION. An earlier version had a chevron BUTTON
 * that expanded a parent separately from its checkbox. It cost a click to reach
 * the thing the menu exists to offer, and it hid seventeen options behind a
 * control most readers never found. It was replaced by rendering every child
 * on every open (twenty-three rows each time). Tick to reveal avoids both
 * costs: there is no extra click, because ticking the parent, which a reader
 * narrowing to a specialty does anyway, is what opens it. The chevron is only a
 * cue that the row opens.
 *
 * THREE UNDOCUMENTED MUI `SelectInput` MECHANICS ARE LOAD-BEARING HERE, all
 * three verified against @mui/material 7.3.6:
 *
 * 1. DIRECT CHILDREN ONLY. `React.Children.toArray(children)` runs over the
 *    immediate children and a Fragment child triggers a `console.error`. The
 *    parent+children rows are therefore emitted as one FLAT array via
 *    `flatMap`, never as nested fragments.
 * 2. `child.props.onClick` FIRES BEFORE `setValueState`. A click anywhere inside
 *    a MenuItem reaches the cloned `handleItemClick` and toggles the row. This
 *    is why no interactive control may be nested inside a row: it would select
 *    the row as a side effect. The old chevron BUTTON needed three separate
 *    stopPropagation handlers to survive it. Today's chevron is an aria-hidden
 *    icon with no handler, so a click on it toggles the row like a click
 *    anywhere else in it.
 * 3. `renderValue` SHORT-CIRCUITS the display computation, so the closed field
 *    draws its parent and child chips from the selection props, not from MUI's
 *    own walk over the menu rows.
 *
 * The test file spies on `console.error` and asserts ZERO calls, which is what
 * makes a future MUI major breaking any of the three fail loudly.
 *
 * SLUG NAMESPACE COLLISION. The control partitions the merged selection by
 * membership in the CHILD slug set. If a subcategory slug were ever minted equal
 * to a category slug, selections would route to the wrong field SILENTLY. The
 * guard is `__tests__/constants/enrichment.test.ts`'s collision assertion, and
 * it has to stay a test.
 */
export function FacetTreeMultiSelect({
  label,
  options,
  childOptions,
  value,
  childValue,
  onChange,
  size = 'small',
}: FacetTreeMultiSelectProps) {
  const labelId = useId();
  const selectedParents = value ?? [];
  const selectedChildren = childValue ?? [];

  const childSlugs = new Set(childOptions.map((opt) => opt.slug));
  const parentOfChild = new Map(
    childOptions.map((opt) => [opt.slug, opt.parentSlug ?? ''] as const)
  );
  const labelBySlug = new Map(
    [...options, ...childOptions].map((opt) => [opt.slug, opt.label] as const)
  );

  const childrenOf = (parentSlug: string) =>
    childOptions.filter((opt) => opt.parentSlug === parentSlug);

  const ownsSelectedChild = (parentSlug: string) =>
    selectedChildren.some((slug) => parentOfChild.get(slug) === parentSlug);

  // With NO children on offer this control IS the flat select, and it has to be
  // inert in both directions:
  //
  //  - the stored child selection stays OUT of the displayed value, or the
  //    closed field would show a raw slug for an option this control cannot
  //    label, let alone offer;
  //  - and it is PRESERVED on emit rather than recomputed, or every category
  //    click would silently clear a subcategory the user saved while the reveal
  //    flag was on. That flag is a UI switch; flipping it off must not destroy
  //    data.
  const treeEnabled = childOptions.length > 0;

  // ONE array for the Select's value.
  const merged = treeEnabled ? [...selectedParents, ...selectedChildren] : [...selectedParents];

  // The chips, in the menu's order: each parent, then its own ticked children,
  // so a child's chip (its own name only) sits beside the parent it narrows. A
  // stored child whose parent is not selected (see AUTO-CHECK) goes last.
  const chipSlugs = treeEnabled
    ? [
        ...selectedParents.flatMap((parent) => [
          parent,
          ...selectedChildren.filter((child) => parentOfChild.get(child) === parent),
        ]),
        ...selectedChildren.filter(
          (child) => !selectedParents.includes(parentOfChild.get(child) ?? '')
        ),
      ]
    : selectedParents;

  const handleChange = (raw: string[] | string) => {
    // MUI can hand back a comma-joined string on native events; normalize.
    const next = typeof raw === 'string' ? raw.split(',') : raw;
    const nextSet = new Set(next);
    const removed = new Set(merged.filter((slug) => !nextSet.has(slug)));

    let categories = next.filter((slug) => !childSlugs.has(slug));

    // UNTICK CLEARS. A parent unticked in this change takes its children with
    // it, so the one emit below is the whole "untick, clear, hide".
    const subcategories = next.filter((slug) => {
      if (!childSlugs.has(slug)) return false;
      const parent = parentOfChild.get(slug);
      return !(parent && removed.has(parent));
    });

    // AUTO-CHECK. Any surviving child implies its parent.
    for (const child of subcategories) {
      const parent = parentOfChild.get(child);
      if (parent && !categories.includes(parent)) categories = [...categories, parent];
    }

    onChange({
      category: categories,
      subcategory: treeEnabled ? subcategories : selectedChildren,
    });
  };

  return (
    <FormControl size={size} sx={{ minWidth: 170 }}>
      <InputLabel id={labelId} shrink>
        {label}
      </InputLabel>
      <Select
        labelId={labelId}
        multiple
        displayEmpty
        value={merged}
        input={<OutlinedInput notched label={label} />}
        MenuProps={{ PaperProps: { sx: { maxHeight: MENU_MAX_HEIGHT } } }}
        onChange={(e) => handleChange(e.target.value)}
        renderValue={(sel) =>
          sel.length === 0 ? (
            'All'
          ) : (
            <FacetValueChips
              values={chipSlugs.map((slug) => ({ slug, label: labelBySlug.get(slug) ?? slug }))}
              // The same edit as unticking the row, so UNTICK CLEARS holds.
              onDelete={(slug) => handleChange(merged.filter((s) => s !== slug))}
            />
          )
        }
      >
        {/* FLAT array — see mechanic 1 in the module comment. */}
        {options.flatMap((opt) => {
          const kids = childrenOf(opt.slug);
          const parentChecked = selectedParents.includes(opt.slug);
          const open = parentChecked && kids.length > 0;

          const parentRow = (
            <MenuItem key={opt.slug} value={opt.slug}>
              <Checkbox
                checked={parentChecked}
                indeterminate={parentChecked && ownsSelectedChild(opt.slug)}
                size="small"
              />
              <ListItemText
                primary={
                  kids.length === 0 ? (
                    opt.label
                  ) : (
                    <>
                      {opt.label}
                      <Box component="span" sx={VISUALLY_HIDDEN_SX}>
                        , {kids.length} {kids.length === 1 ? 'specialty' : 'specialties'}
                      </Box>
                    </>
                  )
                }
              />
              {kids.length > 0 && (
                // A cue, not a control: no handler, hidden from assistive tech
                // (see mechanic 2). It turns when the row opens.
                <Box
                  component="span"
                  aria-hidden
                  data-testid="facet-tree-chevron"
                  sx={{
                    display: 'inline-flex',
                    ml: 1,
                    color: 'text.secondary',
                    transition: 'transform .18s ease',
                    transform: open ? 'rotate(180deg)' : 'none',
                    '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
                  }}
                >
                  <ExpandMoreIcon fontSize="small" />
                </Box>
              )}
            </MenuItem>
          );

          if (!open) return [parentRow];

          return [
            parentRow,
            ...kids.map((kid) => (
              <MenuItem key={kid.slug} value={kid.slug} sx={{ pl: 4 }}>
                <Checkbox checked={selectedChildren.includes(kid.slug)} size="small" />
                <ListItemText primary={kid.label} />
              </MenuItem>
            )),
          ];
        })}
      </Select>
    </FormControl>
  );
}
