import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FacetSelect } from '../../../../components/shared/filters/FacetSelect';
import type { FacetOption } from '../../../../types';

const OPTIONS: FacetOption[] = [
  { slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 },
  { slug: 'growth', label: 'Growth', sortOrder: 1 },
];

describe('FacetSelect', () => {
  it('marks the "All" option selected when value is undefined', async () => {
    const user = userEvent.setup();
    render(<FacetSelect label="Category" options={OPTIONS} value={undefined} onChange={vi.fn()} />);

    // The component maps undefined -> '' (MUI needs a concrete value) but does
    // NOT set `displayEmpty`, so the CLOSED combobox is blank in the cleared
    // state; the "All" option carries the selection. The labelId wiring exposes
    // the accessible name for the query (mirrors TimeWindowSelect).
    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getByRole('option', { name: 'All' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
  });

  it('calls onChange with the slug when an option is selected', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetSelect label="Category" options={OPTIONS} value={undefined} onChange={onChange} />
    );

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Growth' }));

    expect(onChange).toHaveBeenCalledWith('growth');
  });

  it('calls onChange with undefined when "All" is selected', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<FacetSelect label="Category" options={OPTIONS} value="growth" onChange={onChange} />);

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'All' }));

    expect(onChange).toHaveBeenCalledWith(undefined);
  });
});
