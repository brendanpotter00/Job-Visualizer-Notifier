import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SoftwareOnlyToggle } from '../../../../components/shared/filters/SoftwareOnlyToggle';

describe('SoftwareOnlyToggle', () => {
  it('renders default label when none provided', () => {
    render(<SoftwareOnlyToggle checked={false} onChange={vi.fn()} />);
    expect(
      screen.getByRole('switch', { name: 'Software engineering roles only' })
    ).toBeInTheDocument();
  });

  it('renders custom label when provided', () => {
    render(<SoftwareOnlyToggle checked={false} onChange={vi.fn()} label="Custom label" />);
    expect(screen.getByRole('switch', { name: 'Custom label' })).toBeInTheDocument();
  });

  it('reflects checked=true via aria-checked', () => {
    render(<SoftwareOnlyToggle checked={true} onChange={vi.fn()} />);
    // MUI Switch exposes role="switch"
    const toggle = screen.getByRole('switch');
    expect(toggle).toBeChecked();
  });

  it('reflects checked=false via aria-checked', () => {
    render(<SoftwareOnlyToggle checked={false} onChange={vi.fn()} />);
    const toggle = screen.getByRole('switch');
    expect(toggle).not.toBeChecked();
  });

  it('calls onChange when toggled on', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<SoftwareOnlyToggle checked={false} onChange={onChange} />);
    await user.click(screen.getByRole('switch'));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it('calls onChange when toggled off', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<SoftwareOnlyToggle checked={true} onChange={onChange} />);
    await user.click(screen.getByRole('switch'));
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
