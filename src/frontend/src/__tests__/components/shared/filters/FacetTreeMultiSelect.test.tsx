import { useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FacetTreeMultiSelect } from '../../../../components/shared/filters/FacetTreeMultiSelect';
import type { FacetOption } from '../../../../types';

// GENERIC fixture labels, matching FacetMultiSelect.test.tsx's convention — the
// component knows nothing about the SWE taxonomy and its tests must not either.
const PARENTS: FacetOption[] = [
  { slug: 'parent_a', label: 'Category A', sortOrder: 0 },
  { slug: 'parent_b', label: 'Category B', sortOrder: 1 },
];

const CHILDREN: FacetOption[] = [
  { slug: 'child_a', label: 'Child A', sortOrder: 0, parentSlug: 'parent_a' },
  { slug: 'child_b', label: 'Child B', sortOrder: 1, parentSlug: 'parent_a' },
];

// `parent_b` deliberately has NO children, so "a chevron appears" is never a
// property of the control and always a property of the row.

const CHEVRON = 'facet-tree-chevron';

type Selection = { category: string[]; subcategory: string[] };

/**
 * A controlled wrapper that applies each emit, so a test can watch the menu
 * react to its own clicks (rows appearing and disappearing). The props-only
 * renders below cannot: their `value` never moves.
 */
function Stateful({
  initial,
  onChange,
  options = PARENTS,
  childOptions = CHILDREN,
}: {
  initial: Selection;
  onChange: (next: Selection) => void;
  options?: FacetOption[];
  childOptions?: FacetOption[];
}) {
  const [selection, setSelection] = useState(initial);
  return (
    <FacetTreeMultiSelect
      label="Job Category"
      options={options}
      childOptions={childOptions}
      value={selection.category}
      childValue={selection.subcategory}
      onChange={(next) => {
        onChange(next);
        setSelection(next);
      }}
    />
  );
}

/** The closed field's chips (each one is a MUI Chip, so a `button`), by label. */
function chipLabels(): string[] {
  return within(screen.getByRole('combobox', { name: 'Job Category' }))
    .queryAllByRole('button')
    .map((chip) => chip.textContent ?? '');
}

/** Click one chip's delete icon. */
async function deleteChip(user: ReturnType<typeof userEvent.setup>, label: string) {
  const combobox = screen.getByRole('combobox', { name: 'Job Category' });
  const chip = within(combobox).getByRole('button', { name: label });
  await user.click(within(chip).getByTestId('CancelIcon'));
}

/** Every row's text in menu order. A parent with children carries its hidden count. */
function rowTexts(listbox: HTMLElement): string[] {
  return within(listbox)
    .getAllByRole('option')
    .map((row) => row.textContent ?? '');
}

describe('FacetTreeMultiSelect', () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // MUI's Select warns via console.error on a Fragment child, and the
    // component's flat-array shape is exactly what avoids that. Spying here
    // makes a future MUI major that changes the cloning rules fail LOUDLY
    // instead of degrading in silence.
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('combobox', { name: 'Job Category' }));
    return screen.findByRole('listbox');
  }

  it('(1) renders identically to the flat control when childOptions is empty', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={[]}
        value={undefined}
        childValue={undefined}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByRole('combobox', { name: 'Job Category' })).toHaveTextContent('All');
    const listbox = await openMenu(user);

    expect(rowTexts(listbox)).toEqual(['Category A', 'Category B']);
    expect(within(listbox).queryByRole('button')).toBeNull();
    expect(within(listbox).queryByTestId(CHEVRON)).toBeNull();
  });

  it('(1b) with childOptions empty, a stored childValue is neither shown nor destroyed', async () => {
    // The flag-off state, and it must be inert in BOTH directions. Showing the
    // stored slug would render an unlabelled raw string in the closed field;
    // recomputing it on emit would silently clear a selection the user saved
    // while the flag was on. A UI switch must not destroy data.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={[]}
        value={['parent_a']}
        childValue={['child_a']}
        onChange={onChange}
      />
    );

    const combobox = screen.getByRole('combobox', { name: 'Job Category' });
    expect(chipLabels()).toEqual(['Category A']);
    expect(combobox).not.toHaveTextContent('child_a');

    await user.click(combobox);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: /Category B/ }));

    expect(onChange).toHaveBeenCalledWith({
      category: ['parent_a', 'parent_b'],
      subcategory: ['child_a'],
    });
  });

  it('(1c) with childOptions empty, unticking a parent still preserves the stored childValue', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={[]}
        value={['parent_a']}
        childValue={['child_a']}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: /Category A/ }));

    // The untick-clears rule is a TREE rule. With the tree off it must not
    // reach into a selection this control cannot even show.
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: [], subcategory: ['child_a'] });
  });

  it('(2) a parent with no children gets no chevron and no hidden count', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={vi.fn()}
      />
    );

    const listbox = await openMenu(user);
    const parentB = within(listbox).getByRole('option', { name: 'Category B' });
    expect(within(parentB).queryByTestId(CHEVRON)).toBeNull();
    expect(within(parentB).queryByRole('button')).toBeNull();
  });

  it('(3) children stay HIDDEN while their parent is unticked', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={vi.fn()}
      />
    );

    const listbox = await openMenu(user);
    // Just the parent rows.
    expect(rowTexts(listbox)).toEqual(['Category A, 2 specialties', 'Category B']);
    expect(within(listbox).queryByRole('option', { name: /Child/ })).toBeNull();

    // The parent says what ticking it will reveal, to a screen reader only, and
    // carries a closed chevron that is a cue, not a control.
    const parentA = within(listbox).getByRole('option', { name: 'Category A, 2 specialties' });
    const chevron = within(parentA).getByTestId(CHEVRON);
    expect(chevron).toHaveAttribute('aria-hidden', 'true');
    expect(chevron).toHaveStyle({ transform: 'none' });
    expect(within(parentA).queryByRole('button')).toBeNull();
  });

  it('(4) ticking the parent reveals its children right under it, and turns the chevron', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Stateful initial={{ category: [], subcategory: [] }} onChange={onChange} />);

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: /Category A/ }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: ['parent_a'], subcategory: [] });

    // Indented under their parent, BEFORE the next parent.
    expect(rowTexts(listbox)).toEqual([
      'Category A, 2 specialties',
      'Child A',
      'Child B',
      'Category B',
    ]);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    expect(within(parentA).getByTestId(CHEVRON)).toHaveStyle({ transform: 'rotate(180deg)' });
  });

  it('(4b) a click on the chevron is a click on the row: it ticks the parent', async () => {
    // Mechanic 2: the chevron has no handler of its own, so the row's cloned
    // onClick is what fires. A chevron that swallowed the click (or toggled
    // something else) would bring back the old accordion's trap.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Stateful initial={{ category: [], subcategory: [] }} onChange={onChange} />);

    const listbox = await openMenu(user);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    await user.click(within(parentA).getByTestId(CHEVRON));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: ['parent_a'], subcategory: [] });
    expect(within(listbox).getByRole('option', { name: 'Child A' })).toBeInTheDocument();
  });

  it('(5) opening with the parent already ticked shows its children straight away', async () => {
    // The saved-filters case: the menu was never used this session, the
    // selection arrived as props, and the reader must see where it lives.
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={['child_a']}
        onChange={vi.fn()}
      />
    );

    const listbox = await openMenu(user);
    expect(rowTexts(listbox)).toEqual([
      'Category A, 2 specialties',
      'Child A',
      'Child B',
      'Category B',
    ]);
    expect(
      within(within(listbox).getByRole('option', { name: 'Child A' })).getByRole('checkbox')
    ).toBeChecked();
    expect(
      within(within(listbox).getByRole('option', { name: 'Child B' })).getByRole('checkbox')
    ).not.toBeChecked();
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    expect(within(parentA).getByTestId(CHEVRON)).toHaveStyle({ transform: 'rotate(180deg)' });
  });

  it('(6) ticking a revealed child emits both arrays in one call', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={[]}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: 'Child A' }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({
      category: ['parent_a'],
      subcategory: ['child_a'],
    });
  });

  it('(7) unticking a parent with ticked children unticks, clears and hides them in ONE emit', async () => {
    // A second tree (parent_c) is the control: its child must SURVIVE, or the
    // rule is "clear every child", not "clear this parent's children".
    const options: FacetOption[] = [
      ...PARENTS,
      { slug: 'parent_c', label: 'Category C', sortOrder: 2 },
    ];
    const childOptions: FacetOption[] = [
      ...CHILDREN,
      { slug: 'child_c', label: 'Child C', sortOrder: 2, parentSlug: 'parent_c' },
    ];
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Stateful
        options={options}
        childOptions={childOptions}
        initial={{ category: ['parent_a', 'parent_c'], subcategory: ['child_a', 'child_c'] }}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: /Category A/ }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: ['parent_c'], subcategory: ['child_c'] });

    // Collapsed: Category A's children are gone, Category C's are still open.
    expect(rowTexts(listbox)).toEqual([
      'Category A, 2 specialties',
      'Category B',
      'Category C, 1 specialty',
      'Child C',
    ]);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    expect(within(parentA).getByRole('checkbox')).not.toBeChecked();
    expect(within(parentA).getByTestId(CHEVRON)).toHaveStyle({ transform: 'none' });
  });

  it('(7b) clicking a checked parent with NO selected children unchecks it', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={[]}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: /Category A/ }));

    expect(onChange).toHaveBeenCalledWith({ category: [], subcategory: [] });
  });

  it('(8) AUTO-CHECK still holds: a stored child with no parent brings its parent on the next emit', async () => {
    // The menu can no longer offer a child under an unticked parent, but stored
    // data can still arrive that way. Whatever the reader clicks next, the emit
    // is made consistent: a child never leaves without its parent.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={[]}
        childValue={['child_a']}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: 'Category B' }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({
      category: ['parent_b', 'parent_a'],
      subcategory: ['child_a'],
    });
  });

  it('(9) the parent checkbox is indeterminate when it is checked and a child is ticked', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={['child_a']}
        onChange={vi.fn()}
      />
    );

    const listbox = await openMenu(user);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    expect(within(parentA).getByRole('checkbox')).toHaveAttribute('data-indeterminate', 'true');

    const parentB = within(listbox).getByRole('option', { name: /Category B/ });
    expect(within(parentB).getByRole('checkbox')).toHaveAttribute('data-indeterminate', 'false');
  });

  it('(10) keyboard: Enter ticks the parent, ArrowDown reaches the revealed child, Enter ticks it', async () => {
    // The revealed children are ordinary MenuItems in the same list, so MUI's
    // own roving focus must reach them with no extra wiring.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<Stateful initial={{ category: [], subcategory: [] }} onChange={onChange} />);

    const listbox = await openMenu(user);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    expect(parentA).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(onChange).toHaveBeenLastCalledWith({ category: ['parent_a'], subcategory: [] });
    expect(parentA).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    const childA = within(listbox).getByRole('option', { name: 'Child A' });
    expect(childA).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(onChange).toHaveBeenLastCalledWith({
      category: ['parent_a'],
      subcategory: ['child_a'],
    });

    // Past the children, the next parent is still one ArrowDown away from the last child.
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(within(listbox).getByRole('option', { name: 'Category B' })).toHaveFocus();
  });

  it('(11) renders the placeholder when nothing is selected, and labels when something is', () => {
    const { rerender } = render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByRole('combobox', { name: 'Job Category' })).toHaveTextContent('All');

    rerender(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={['child_a']}
        onChange={vi.fn()}
      />
    );
    // One chip each, the parent first — and LABELS, never slugs. The hidden
    // specialty count lives in the menu row only, never in the closed field.
    expect(chipLabels()).toEqual(['Category A', 'Child A']);
    expect(screen.getByRole('combobox', { name: 'Job Category' })).toHaveTextContent(
      /^Category AChild A$/
    );
  });

  it("(12) each parent's chip is followed by its own children's, whatever order they were picked in", () => {
    // Picked Category B, then Category A, then Child A. A child's chip carries
    // only its own name, so it has to sit beside its parent, not after the
    // last parent picked.
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a', 'parent_b']}
        childValue={['child_b', 'child_a']}
        onChange={vi.fn()}
      />
    );
    expect(chipLabels()).toEqual(['Category A', 'Child B', 'Child A', 'Category B']);
  });

  it('(12b) a stored child with no parent selected still gets its chip, last', () => {
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_b']}
        childValue={['child_a']}
        onChange={vi.fn()}
      />
    );
    expect(chipLabels()).toEqual(['Category B', 'Child A']);
  });

  it("(13) a child chip's delete icon removes just the child; its parent stays, the menu stays shut", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Stateful
        initial={{ category: ['parent_a'], subcategory: ['child_a', 'child_b'] }}
        onChange={onChange}
      />
    );

    await deleteChip(user, 'Child A');

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: ['parent_a'], subcategory: ['child_b'] });
    expect(chipLabels()).toEqual(['Category A', 'Child B']);
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it("(14) a parent chip's delete icon is an untick: it clears that parent's children, in ONE emit", async () => {
    // The same rule as (7), through the chip. Category C's child is the control.
    const options: FacetOption[] = [
      ...PARENTS,
      { slug: 'parent_c', label: 'Category C', sortOrder: 2 },
    ];
    const childOptions: FacetOption[] = [
      ...CHILDREN,
      { slug: 'child_c', label: 'Child C', sortOrder: 2, parentSlug: 'parent_c' },
    ];
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <Stateful
        options={options}
        childOptions={childOptions}
        initial={{ category: ['parent_a', 'parent_c'], subcategory: ['child_a', 'child_c'] }}
        onChange={onChange}
      />
    );
    expect(chipLabels()).toEqual(['Category A', 'Child A', 'Category C', 'Child C']);

    await deleteChip(user, 'Category A');

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: ['parent_c'], subcategory: ['child_c'] });
    expect(chipLabels()).toEqual(['Category C', 'Child C']);
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('(14b) with childOptions empty, deleting a parent chip still preserves the stored childValue', async () => {
    // (1c) through the chip: the tree is off, so the untick-clears rule is too.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={[]}
        value={['parent_a', 'parent_b']}
        childValue={['child_a']}
        onChange={onChange}
      />
    );

    await deleteChip(user, 'Category A');

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: ['parent_b'], subcategory: ['child_a'] });
  });

  it('(15) the chips are not tab stops, and a click on a chip body opens the menu', async () => {
    const user = userEvent.setup();
    render(
      <>
        <FacetTreeMultiSelect
          label="Job Category"
          options={PARENTS}
          childOptions={CHILDREN}
          value={['parent_a']}
          childValue={['child_a']}
          onChange={vi.fn()}
        />
        <button type="button">After</button>
      </>
    );

    const combobox = screen.getByRole('combobox', { name: 'Job Category' });
    await user.tab();
    expect(combobox).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus();

    await user.click(within(combobox).getByRole('button', { name: 'Child A' }));
    expect(await screen.findByRole('listbox')).toBeInTheDocument();
  });
});
