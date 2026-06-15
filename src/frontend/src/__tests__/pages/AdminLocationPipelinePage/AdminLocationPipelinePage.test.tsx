import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AdminLocationPipelinePage } from '../../../pages/AdminLocationPipelinePage/AdminLocationPipelinePage';

describe('AdminLocationPipelinePage', () => {
  it('renders the heading, the stage nodes, and the first example input', () => {
    render(<AdminLocationPipelinePage />);
    expect(
      screen.getByRole('heading', { name: /location pipeline/i, level: 1 })
    ).toBeInTheDocument();
    expect(screen.getByText('normalize_string')).toBeInTheDocument();
    expect(screen.getByText('Tier-2 Haiku 4.5')).toBeInTheDocument();
    expect(screen.getByText('Persist')).toBeInTheDocument();
    expect(screen.getByText('Austin, TX, USA; Atlanta, GA, USA')).toBeInTheDocument();
    expect(screen.getByText(/Stage 1 \/ 7/)).toBeInTheDocument();
  });

  it('advances the stage counter with the step-forward control', async () => {
    const user = userEvent.setup();
    render(<AdminLocationPipelinePage />);
    await user.click(screen.getByRole('button', { name: /step forward/i }));
    expect(screen.getByText(/Stage 2 \/ 7/)).toBeInTheDocument();
  });

  it('switches examples and reflects the new raw input', async () => {
    const user = userEvent.setup();
    render(<AdminLocationPipelinePage />);
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: /scoped eu/i }));
    expect(screen.getByText('Remote - EU')).toBeInTheDocument();
  });

  it('ends the low-confidence example as failed with four empty tables', async () => {
    const user = userEvent.setup();
    render(<AdminLocationPipelinePage />);
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: /garbage/i }));

    const forward = screen.getByRole('button', { name: /step forward/i });
    for (let i = 0; i < 4; i++) await user.click(forward);

    expect(screen.getByText('status: failed')).toBeInTheDocument();
    // No rows are written on a failed run — all four tables stay empty.
    expect(screen.getAllByText('empty')).toHaveLength(4);
  });
});
