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

/** The closed field's chips (each one is a MUI Chip, so a `button`), by label. */
function chipLabels(combobox: HTMLElement): string[] {
  return within(combobox)
    .queryAllByRole('button')
    .map((chip) => chip.textContent ?? '');
}

function chip(combobox: HTMLElement, label: string): HTMLElement {
  return within(combobox).getByRole('button', { name: label });
}

describe('FacetMultiSelect', () => {
  it('renders "All" and exposes the combobox by its label when nothing is selected', () => {
    render(
      <FacetMultiSelect label="Category" options={OPTIONS} value={undefined} onChange={vi.fn()} />
    );
    const combobox = screen.getByRole('combobox', { name: 'Category' });
    expect(combobox).toHaveTextContent('All');
    expect(chipLabels(combobox)).toEqual([]);
  });

  it('shows each selected option as a chip with its label, not its slug', () => {
    render(
      <FacetMultiSelect
        label="Category"
        options={OPTIONS}
        value={['software_engineering', 'growth']}
        onChange={vi.fn()}
      />
    );
    // The chips do not change the field's accessible name: it is the label alone.
    const combobox = screen.getByRole('combobox', { name: 'Category' });
    expect(chipLabels(combobox)).toEqual(['Software Engineering', 'Growth']);
    expect(combobox).not.toHaveTextContent('All');
    expect(combobox).not.toHaveTextContent(',');
  });

  it("a chip's delete icon removes just that value and does not open the menu", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetMultiSelect
        label="Category"
        options={OPTIONS}
        value={['software_engineering', 'growth']}
        onChange={onChange}
      />
    );

    const combobox = screen.getByRole('combobox', { name: 'Category' });
    await user.click(within(chip(combobox, 'Growth')).getByTestId('CancelIcon'));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(['software_engineering']);
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(combobox).toHaveAttribute('aria-expanded', 'false');
  });

  it("deleting the last chip's value emits an empty selection (All)", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetMultiSelect label="Category" options={OPTIONS} value={['growth']} onChange={onChange} />
    );

    const combobox = screen.getByRole('combobox', { name: 'Category' });
    await user.click(within(chip(combobox, 'Growth')).getByTestId('CancelIcon'));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("a click on a chip's body opens the menu, like a click anywhere else on the field", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <FacetMultiSelect label="Category" options={OPTIONS} value={['growth']} onChange={onChange} />
    );

    await user.click(chip(screen.getByRole('combobox', { name: 'Category' }), 'Growth'));

    expect(await screen.findByRole('listbox')).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('the chips are not tab stops: the combobox stays the one stop and still opens from the keyboard', async () => {
    const user = userEvent.setup();
    render(
      <>
        <FacetMultiSelect
          label="Category"
          options={OPTIONS}
          value={['software_engineering', 'growth']}
          onChange={vi.fn()}
        />
        <button type="button">After</button>
      </>
    );

    const combobox = screen.getByRole('combobox', { name: 'Category' });
    await user.tab();
    expect(combobox).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus();

    await user.tab({ shift: true });
    expect(combobox).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(await screen.findByRole('listbox')).toBeInTheDocument();
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
      <FacetMultiSelect label="Category" options={OPTIONS} value={['growth']} onChange={onChange} />
    );

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Growth' }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('marks currently-selected options as aria-selected', async () => {
    const user = userEvent.setup();
    render(
      <FacetMultiSelect label="Category" options={OPTIONS} value={['growth']} onChange={vi.fn()} />
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
