import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SyncFiltersButton } from '../../../../components/shared/filters/SyncFiltersButton';

describe('SyncFiltersButton', () => {
  it('renders "Sync to List" label when direction="toList"', () => {
    render(<SyncFiltersButton direction="toList" onClick={vi.fn()} />);
    expect(screen.getByRole('button', { name: /sync to list/i })).toBeInTheDocument();
  });

  it('renders "Sync to Graph" label when direction="toGraph"', () => {
    render(<SyncFiltersButton direction="toGraph" onClick={vi.fn()} />);
    expect(screen.getByRole('button', { name: /sync to graph/i })).toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<SyncFiltersButton direction="toList" onClick={onClick} />);
    await user.click(screen.getByRole('button', { name: /sync to list/i }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders SyncAlt icon', () => {
    render(<SyncFiltersButton direction="toList" onClick={vi.fn()} />);
    const button = screen.getByRole('button', { name: /sync to list/i });
    // MUI icons expose a data-testid attribute with the icon name
    expect(button.querySelector('[data-testid="SyncAltIcon"]')).toBeInTheDocument();
  });
});
