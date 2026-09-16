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

    expect(within(listbox).getAllByRole('option')).toHaveLength(2);
    expect(within(listbox).queryByRole('button')).toBeNull();
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
    expect(combobox).toHaveTextContent('Category A');
    expect(combobox).not.toHaveTextContent('child_a');

    await user.click(combobox);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: /Category B/ }));

    expect(onChange).toHaveBeenCalledWith({
      category: ['parent_a', 'parent_b'],
      subcategory: ['child_a'],
    });
  });

  it('(2) renders no chevron on a parent that has no children', async () => {
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
    const parentB = within(listbox).getByRole('option', { name: /Category B/ });
    expect(within(parentB).queryByRole('button')).toBeNull();
  });

  it('(3) a parent with children renders its child rows IMMEDIATELY, and no expander', async () => {
    // THE ACCORDION IS GONE. The menu opens showing every child under its
    // parent: no chevron to find, no click between the reader and the options
    // the menu exists to offer. A button anywhere in a row would also re-open
    // the MUI trap this control used to need three stopPropagation handlers for.
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
    expect(within(listbox).getByRole('option', { name: /Child A/ })).toBeInTheDocument();
    expect(within(listbox).getByRole('option', { name: /Child B/ })).toBeInTheDocument();

    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    expect(within(parentA).queryByRole('button')).toBeNull();
  });

  it('(6) ticking a child AUTO-CHECKS its parent and emits both arrays', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: /Child A/ }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({
      category: ['parent_a'],
      subcategory: ['child_a'],
    });
  });

  it('(7) clicking a parent that owns selected children WIDENS: children cleared, parent kept', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job Category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={['child_a']}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    await user.click(within(listbox).getByRole('option', { name: /Category A/ }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ category: ['parent_a'], subcategory: [] });
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

  it('(8) the parent checkbox is indeterminate when it is checked and a child is ticked', async () => {
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

  it('(9) a pre-selected child is checked, and its row needed no expanding', async () => {
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
    const childA = within(listbox).getByRole('option', { name: /Child A/ });
    expect(within(childA).getByRole('checkbox')).toBeChecked();
  });

  it('(10) renders the placeholder when nothing is selected, and labels when something is', () => {
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
    // Parents first, then children — and LABELS, never slugs.
    expect(screen.getByRole('combobox', { name: 'Job Category' })).toHaveTextContent(
      'Category A, Child A'
    );
  });
});
