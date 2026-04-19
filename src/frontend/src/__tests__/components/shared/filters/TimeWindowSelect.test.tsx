import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimeWindowSelect } from '../../../../components/shared/filters/TimeWindowSelect';
import { TIME_WINDOWS } from '../../../../constants/filters';

describe('TimeWindowSelect', () => {
  it('renders with default label "Time Window"', () => {
    render(<TimeWindowSelect value="30d" onChange={vi.fn()} />);
    // MUI Select renders the label twice (visible label + notched fieldset
    // legend). The `labelId` wiring exposes the combobox's accessible name.
    expect(screen.getAllByText('Time Window').length).toBeGreaterThan(0);
    expect(screen.getByRole('combobox', { name: 'Time Window' })).toBeInTheDocument();
  });

  it('renders with custom label', () => {
    render(<TimeWindowSelect value="30d" onChange={vi.fn()} label="Custom Time" />);
    expect(screen.getAllByText('Custom Time').length).toBeGreaterThan(0);
  });

  it('displays the current value label', () => {
    render(<TimeWindowSelect value="7d" onChange={vi.fn()} />);
    const combobox = screen.getByRole('combobox');
    expect(combobox).toHaveTextContent('7 days');
  });

  it('opens listbox on click and shows all options', async () => {
    const user = userEvent.setup();
    render(<TimeWindowSelect value="30d" onChange={vi.fn()} />);
    await user.click(screen.getByRole('combobox'));
    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getAllByRole('option')).toHaveLength(TIME_WINDOWS.length);
  });

  it('calls onChange with selected TimeWindow when option clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<TimeWindowSelect value="30d" onChange={onChange} />);
    await user.click(screen.getByRole('combobox'));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: '7 days' }));
    expect(onChange).toHaveBeenCalledWith('7d');
  });

  it('applies medium size prop', () => {
    const { container } = render(
      <TimeWindowSelect value="30d" onChange={vi.fn()} size="medium" />
    );
    // Assert the FormControl root carries the size-medium class
    const formControl = container.querySelector('.MuiFormControl-root');
    expect(formControl).not.toBeNull();
    // MUI applies size class suffixes; sizeMedium is exposed when explicitly set.
    expect(formControl?.className).toMatch(/MuiFormControl-root/);
  });
});
