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

  it('dims/skips the LLM, floor and canonicalize nodes on the cache-HIT branch', async () => {
    const user = userEvent.setup();
    const { container } = render(<AdminLocationPipelinePage />);
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: /cache hit/i }));

    // HIT path is [0,1,2,6]: step to persist (3 advances from raw).
    const forward = screen.getByRole('button', { name: /step forward/i });
    for (let i = 0; i < 3; i++) await user.click(forward);

    // Stages 3 (LLM), 4 (floor), 5 (canonicalize) are not on the path → skipped.
    const skipped = container.querySelectorAll('[data-stage-state="skipped"]');
    expect(skipped).toHaveLength(3);

    // The visited stages render as done/active (raw/normalize/tier1 done, persist active).
    const done = container.querySelectorAll('[data-stage-state="done"]');
    expect(done).toHaveLength(3);
    const active = container.querySelectorAll('[data-stage-state="active"]');
    expect(active).toHaveLength(1);
  });

  it('reaches a done terminal state on the MISS example: rows fill, done pill + outcome note show', async () => {
    const user = userEvent.setup();
    render(<AdminLocationPipelinePage />);

    // Default example is the MISS multi-location run; step the full 7-stage path.
    const forward = screen.getByRole('button', { name: /step forward/i });
    for (let i = 0; i < 6; i++) await user.click(forward);

    // A persisted row string is now visible (rows only render on a done run).
    expect(screen.getByText('Austin, TX, US')).toBeInTheDocument();
    // The status pill flips to done.
    expect(screen.getByText('status: done')).toBeInTheDocument();
    // The terminal outcome note appears.
    expect(
      screen.getByText(/Two cities → two canonical rows; position 0 is the primary location\./)
    ).toBeInTheDocument();
  });

  it('reaches the deferred terminal state on the no-key example', async () => {
    const user = userEvent.setup();
    render(<AdminLocationPipelinePage />);
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: /no api key/i }));

    // no-key path is [0,1,2,3]: step to the LLM stage (3 advances from raw).
    const forward = screen.getByRole('button', { name: /step forward/i });
    for (let i = 0; i < 3; i++) await user.click(forward);

    expect(screen.getByText('status: NULL (deferred)')).toBeInTheDocument();
  });

  it('shows the failed-stage In→Out detail on the confidence floor of the garbage example', async () => {
    const user = userEvent.setup();
    render(<AdminLocationPipelinePage />);
    await user.click(screen.getByRole('combobox'));
    await user.click(await screen.findByRole('option', { name: /garbage/i }));

    // fail path is [0,1,2,3,4]: step to the confidence floor (4 advances from raw).
    const forward = screen.getByRole('button', { name: /step forward/i });
    for (let i = 0; i < 4; i++) await user.click(forward);

    // The detail panel's Out text exercises the isFailed styling path. RTL
    // collapses the fixture's double space to a single space before matching.
    expect(screen.getByText('0.22 < 0.50 ✗ → status = failed, nothing cached')).toBeInTheDocument();
  });

  it('shows a normal stage In→Out detail on the MISS example normalize stage', async () => {
    const user = userEvent.setup();
    render(<AdminLocationPipelinePage />);

    // Default MISS example, step once to the normalize stage.
    await user.click(screen.getByRole('button', { name: /step forward/i }));

    expect(screen.getByText('"austin, tx, usa; atlanta, ga, usa"')).toBeInTheDocument();
  });
});
