import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { LandingPage } from '../../../pages/LandingPage/LandingPage';
import type { LandingPrototypeProps } from '../../../pages/LandingPage/types';

// Mock at the lazy boundary: vi.mock intercepts the dynamic import() inside
// React.lazy, so the shell's own contract (fixture toggle, prop plumbing, the
// Suspense boundary) is exercised without mounting the scene — which would drag
// three/rapier into the test process and defeat the point of the boundary.
vi.mock('../../../pages/LandingPage/prototypes/GravityPrototype/GravityPrototype', () => ({
  default: (props: LandingPrototypeProps) => (
    <div data-testid="landing-body">
      gravity ({props.sparse ? 'sparse' : 'rich'}, {props.jobs.length} jobs, now={props.now})
    </div>
  ),
}));

function renderPage(url = '/landing') {
  return renderWithProviders(<LandingPage />, { initialEntries: [url] });
}

describe('LandingPage', () => {
  it('renders the Gravity landing body behind a Suspense boundary', async () => {
    renderPage();
    expect(await screen.findByTestId('landing-body')).toHaveTextContent(/gravity \(rich/);
  });

  // The four-tab workspace is gone (2026-09-03 consolidation). There is exactly
  // one design now, so any tab chrome coming back is a regression, not a
  // feature — assert its absence rather than trusting the deletion to stick.
  it('renders no prototype tab chrome', async () => {
    renderPage();
    await screen.findByTestId('landing-body');
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
  });

  it('?data=sparse swaps in the sparse fixture', async () => {
    renderPage('/landing?data=sparse');
    expect(await screen.findByTestId('landing-body')).toHaveTextContent(/gravity \(sparse/);
  });

  it('any other ?data= value keeps the rich fixture', async () => {
    renderPage('/landing?data=nonsense');
    expect(await screen.findByTestId('landing-body')).toHaveTextContent(/gravity \(rich/);
  });

  // Fixtures and "now" are threaded from the shell so nothing below it samples
  // Date.now() during render (react-hooks/purity) and so the two fixtures stay
  // genuinely different sets rather than the same list twice.
  it('hands the body a non-empty fixture and the shared render clock', async () => {
    renderPage();
    const body = await screen.findByTestId('landing-body');
    const jobs = Number(/(\d+) jobs/.exec(body.textContent ?? '')?.[1]);
    const now = Number(/now=(\d+)/.exec(body.textContent ?? '')?.[1]);
    expect(jobs).toBeGreaterThan(0);
    expect(now).toBeGreaterThan(0);
  });
});
