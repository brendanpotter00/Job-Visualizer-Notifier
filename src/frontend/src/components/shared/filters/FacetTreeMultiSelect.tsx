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

/**
 * Cap on the open menu's height.
 *
 * UNMEASURED — placeholder; set by FE-UI-1
 *
 * There is no maxHeight on the flat `FacetMultiSelect` today because six
 * category rows fit anywhere. Six parents plus seventeen children is twenty-three
 * rows, and since the children are ALWAYS rendered that is the every-time height,
 * not a worst case — it overflows a phone viewport and most laptop ones.
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
   * the locked-parent rule both move the two selections together, and two
   * separate callbacks would let a consumer apply one and drop the other,
   * desyncing a child from its parent with no way to notice.
   */
  onChange: (next: { category: string[]; subcategory: string[] }) => void;
  /** Optional hover hint on the whole control. */
  tooltip?: string;
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
 * - Ticking a child AUTO-CHECKS its parent. A subcategory selection with no
 *   category selection would be filtered out server-side by the category
 *   predicate, so the two are only ever emitted consistently.
 * - Clicking a checked parent that owns selected children CLEARS those children
 *   and leaves the parent checked — one click WIDENS to the whole category. A
 *   second click then unchecks it. (A literally dead click is worse UX.)
 * - CHILDREN ARE ALWAYS RENDERED. There is no expand/collapse: the menu opens
 *   showing every subcategory under its parent, indented. This replaced an
 *   accordion — the chevron cost a click to reach the thing the menu exists to
 *   offer, and hid seventeen options behind a control most readers never found.
 *   Twenty-three rows scroll; `MENU_MAX_HEIGHT` is what makes that survivable.
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
 *    the row as a side effect. The old chevron needed three separate
 *    stopPropagation handlers to survive it; removing it removed that trap.
 * 3. `renderValue` SHORT-CIRCUITS the display computation, so the closed field
 *    shows parent and child labels together from one flat merged array.
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
  tooltip,
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

  // ONE array for the Select. Parents first so `renderValue`'s join reads
  // "Software Engineering, Backend" rather than the other way round.
  const merged = treeEnabled ? [...selectedParents, ...selectedChildren] : [...selectedParents];

  const handleChange = (raw: string[] | string) => {
    // MUI can hand back a comma-joined string on native events; normalize.
    const next = typeof raw === 'string' ? raw.split(',') : raw;
    const nextSet = new Set(next);
    const removed = merged.filter((slug) => !nextSet.has(slug));

    let categories = next.filter((slug) => !childSlugs.has(slug));
    let subcategories = next.filter((slug) => childSlugs.has(slug));

    // THE LOCK. Unchecking a parent that still owns selected children means
    // "widen to the whole category": drop its children, keep it checked.
    for (const slug of removed) {
      if (childSlugs.has(slug)) continue;
      const owned = subcategories.filter((child) => parentOfChild.get(child) === slug);
      if (owned.length === 0) continue;
      subcategories = subcategories.filter((child) => parentOfChild.get(child) !== slug);
      if (!categories.includes(slug)) categories = [...categories, slug];
    }

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

  const control = (
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
          sel.length === 0 ? 'All' : sel.map((slug) => labelBySlug.get(slug) ?? slug).join(', ')
        }
      >
        {/* FLAT array — see mechanic 1 in the module comment. */}
        {options.flatMap((opt) => {
          const kids = childrenOf(opt.slug);
          const parentChecked = selectedParents.includes(opt.slug);

          const parentRow = (
            <MenuItem key={opt.slug} value={opt.slug}>
              <Checkbox
                checked={parentChecked}
                indeterminate={parentChecked && ownsSelectedChild(opt.slug)}
                size="small"
              />
              <ListItemText primary={opt.label} />
            </MenuItem>
          );

          if (kids.length === 0) return [parentRow];

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

  return tooltip ? (
    <Tooltip title={tooltip} placement="top" enterDelay={400}>
      {control}
    </Tooltip>
  ) : (
    control
  );
}
