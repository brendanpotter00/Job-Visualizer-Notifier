import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FacetMultiSelect } from '../../../../components/shared/filters/FacetMultiSelect';
import type { FacetOption } from '../../../../types';

const OPTIONS: FacetOption[] = [
  { slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 },
  { slug: 'hardware_engineer', label: 'Hardware Engineer', sortOrder: 1 },
  { slug: 'growth', label: 'Growth', sortOrder: 2 },
];

describe('FacetMultiSelect', () => {
  it('renders "All" and exposes the combobox by its label when nothing is selected', () => {
    render(
      <FacetMultiSelect label="Category" options={OPTIONS} value={undefined} onChange={vi.fn()} />
    );
    expect(screen.getByRole('combobox', { name: 'Category' })).toHaveTextContent('All');
  });

  it('shows selected options as their labels (joined), not slugs', () => {
    render(
      <FacetMultiSelect
        label="Category"
        options={OPTIONS}
        value={['software_engineering', 'growth']}
        onChange={vi.fn()}
      />
    );
    const combobox = screen.getByRole('combobox', { name: 'Category' });
    expect(combobox).toHaveTextContent('Software Engineering, Growth');
  });

  it('checking an option calls onChange with that slug in an array', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetMultiSelect label="Category" options={OPTIONS} value={undefined} onChange={onChange} />
    );

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Software Engineering' }));

    expect(onChange).toHaveBeenCalledWith(['software_engineering']);
  });

  it('checking a second option appends it to the existing selection', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetMultiSelect
        label="Category"
        options={OPTIONS}
        value={['software_engineering']}
        onChange={onChange}
      />
    );

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Hardware Engineer' }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect([...onChange.mock.calls[0][0]].sort()).toEqual(
      ['hardware_engineer', 'software_engineering'].sort()
    );
  });

  it('unchecking a selected option removes it (empty array when it was the last)', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetMultiSelect
        label="Category"
        options={OPTIONS}
        value={['growth']}
        onChange={onChange}
      />
    );

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Growth' }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('marks currently-selected options as aria-selected', async () => {
    const user = userEvent.setup();
    render(
      <FacetMultiSelect
        label="Category"
        options={OPTIONS}
        value={['growth']}
        onChange={vi.fn()}
      />
    );

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getByRole('option', { name: 'Growth' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    expect(within(listbox).getByRole('option', { name: 'Hardware Engineer' })).toHaveAttribute(
      'aria-selected',
      'false'
    );
  });
});
