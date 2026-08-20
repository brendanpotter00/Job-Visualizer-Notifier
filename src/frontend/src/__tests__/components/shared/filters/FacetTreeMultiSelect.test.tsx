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
    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    return screen.findByRole('listbox');
  }

  it('(1) renders identically to the flat control when childOptions is empty', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={[]}
        value={undefined}
        childValue={undefined}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByRole('combobox', { name: 'Job category' })).toHaveTextContent('All');
    const listbox = await openMenu(user);

    expect(within(listbox).getAllByRole('option')).toHaveLength(2);
    expect(within(listbox).queryByRole('button')).toBeNull();
  });

  it('(2) renders no chevron on a parent that has no children', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job category"
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

  it('(3) renders a collapsed chevron on a parent with children, and no child rows', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={vi.fn()}
      />
    );

    const listbox = await openMenu(user);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    const chevron = within(parentA).getByRole('button');

    expect(chevron).toHaveAttribute('aria-expanded', 'false');
    expect(within(listbox).queryByRole('option', { name: /Child A/ })).toBeNull();
    expect(within(listbox).queryByRole('option', { name: /Child B/ })).toBeNull();
  });

  it('(4) clicking the chevron expands WITHOUT selecting the parent', async () => {
    // THE regression this file exists for. MUI's cloned MenuItem onClick fires
    // before the selection updates, so a chevron click that does not stop
    // propagation both expands the row and ticks its checkbox.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    await user.click(within(parentA).getByRole('button'));

    expect(onChange).not.toHaveBeenCalled();
    expect(within(parentA).getByRole('button')).toHaveAttribute('aria-expanded', 'true');
    expect(within(listbox).getByRole('option', { name: /Child A/ })).toBeInTheDocument();
    expect(within(listbox).getByRole('option', { name: /Child B/ })).toBeInTheDocument();
  });

  it('(5) ArrowRight expands the focused parent and ArrowLeft collapses it', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    parentA.focus();

    await user.keyboard('{ArrowRight}');
    expect(within(listbox).getByRole('option', { name: /Child A/ })).toBeInTheDocument();

    await user.keyboard('{ArrowLeft}');
    expect(within(listbox).queryByRole('option', { name: /Child A/ })).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('(6) ticking a child AUTO-CHECKS its parent and emits both arrays', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={onChange}
      />
    );

    const listbox = await openMenu(user);
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    await user.click(within(parentA).getByRole('button'));
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
        label="Job category"
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
        label="Job category"
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
        label="Job category"
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

  it('(9) mounting with a child pre-selected auto-expands that parent', async () => {
    const user = userEvent.setup();
    render(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={['child_b']}
        onChange={vi.fn()}
      />
    );

    const listbox = await openMenu(user);
    expect(within(listbox).getByRole('option', { name: /Child B/ })).toBeInTheDocument();
    const parentA = within(listbox).getByRole('option', { name: /Category A/ });
    expect(within(parentA).getByRole('button')).toHaveAttribute('aria-expanded', 'true');
  });

  it('(10) renders the placeholder when nothing is selected, and labels when something is', () => {
    const { rerender } = render(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={undefined}
        childValue={undefined}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByRole('combobox', { name: 'Job category' })).toHaveTextContent('All');

    rerender(
      <FacetTreeMultiSelect
        label="Job category"
        options={PARENTS}
        childOptions={CHILDREN}
        value={['parent_a']}
        childValue={['child_a']}
        onChange={vi.fn()}
      />
    );
    // Parents first, then children — and LABELS, never slugs.
    expect(screen.getByRole('combobox', { name: 'Job category' })).toHaveTextContent(
      'Category A, Child A'
    );
  });
});
