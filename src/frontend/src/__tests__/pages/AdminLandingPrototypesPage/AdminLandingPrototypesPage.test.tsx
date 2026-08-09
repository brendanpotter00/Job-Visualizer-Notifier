import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { AdminLandingPrototypesPage } from '../../../pages/AdminLandingPrototypesPage/AdminLandingPrototypesPage';
import type { LandingPrototypeProps } from '../../../pages/AdminLandingPrototypesPage/types';

// Mock all four prototype modules at the lazy boundary: vi.mock intercepts the
// dynamic import() inside React.lazy, so shell tests exercise tab switching,
// URL sync, and prop plumbing without rendering full prototypes (and, later,
// without touching the 3D scenes).
function stub(name: string) {
  return function PrototypeStub(props: LandingPrototypeProps) {
    return (
      <div>
        {name}-stub ({props.sparse ? 'sparse' : 'rich'}, {props.jobs.length} jobs)
      </div>
    );
  };
}
vi.mock('../../../pages/AdminLandingPrototypesPage/prototypes/SignalPrototype/SignalPrototype', () => ({
  default: stub('signal'),
}));
vi.mock('../../../pages/AdminLandingPrototypesPage/prototypes/BoardPrototype/BoardPrototype', () => ({
  default: stub('board'),
}));
vi.mock('../../../pages/AdminLandingPrototypesPage/prototypes/GravityPrototype/GravityPrototype', () => ({
  default: stub('gravity'),
}));
vi.mock('../../../pages/AdminLandingPrototypesPage/prototypes/DriftPrototype/DriftPrototype', () => ({
  default: stub('drift'),
}));

function renderPage(url = '/admin/landing-prototypes') {
  return renderWithProviders(<AdminLandingPrototypesPage />, { initialEntries: [url] });
}

describe('AdminLandingPrototypesPage', () => {
  it('renders all four tabs with Signal active by default', async () => {
    renderPage();
    expect(await screen.findByText(/signal-stub/)).toBeInTheDocument();
    for (const label of ['Signal', 'The Board', 'Gravity', 'Drift']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: 'Signal' })).toHaveAttribute('aria-selected', 'true');
  });

  it('switches prototypes when a tab is clicked', async () => {
    renderPage();
    await screen.findByText(/signal-stub/);
    await userEvent.click(screen.getByRole('tab', { name: 'The Board' }));
    expect(await screen.findByText(/board-stub/)).toBeInTheDocument();
    expect(screen.queryByText(/signal-stub/)).not.toBeInTheDocument();
  });

  it('deep-links a tab via ?proto=', async () => {
    renderPage('/admin/landing-prototypes?proto=drift');
    expect(await screen.findByText(/drift-stub/)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Drift' })).toHaveAttribute('aria-selected', 'true');
  });

  it('falls back to the first tab on an invalid ?proto=', async () => {
    renderPage('/admin/landing-prototypes?proto=nonsense');
    expect(await screen.findByText(/signal-stub/)).toBeInTheDocument();
  });

  it('?data=sparse swaps in the sparse fixture and survives tab switches', async () => {
    renderPage('/admin/landing-prototypes?proto=board&data=sparse');
    expect(await screen.findByText(/board-stub \(sparse/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Gravity' }));
    expect(await screen.findByText(/gravity-stub \(sparse/)).toBeInTheDocument();
  });

  it('offers a back-to-app escape hatch (the page has no drawer)', async () => {
    renderPage();
    await screen.findByText(/signal-stub/);
    expect(screen.getByRole('link', { name: /back to the app/i })).toHaveAttribute('href', '/');
  });
});
