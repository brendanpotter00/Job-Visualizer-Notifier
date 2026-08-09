import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { BoardPrototype } from '../../../pages/AdminLandingPrototypesPage/prototypes/BoardPrototype/BoardPrototype';
import { LANDING_CONTENT } from '../../../pages/AdminLandingPrototypesPage/content';
import { buildMockJobs, buildSparseMockJobs, MOCK_STATS } from '../../../pages/AdminLandingPrototypesPage/mockData';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();

function renderBoard(sparse = false) {
  return renderWithProviders(
    <BoardPrototype
      content={LANDING_CONTENT}
      jobs={sparse ? buildSparseMockJobs(NOW) : buildMockJobs(NOW)}
      stats={MOCK_STATS}
      sparse={sparse}
      now={NOW}
    />,
    { initialEntries: ['/admin/landing-prototypes'] }
  );
}

describe('BoardPrototype', () => {
  it('renders the anti-noise hero and embedded job cards with Apply links', () => {
    renderBoard();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      LANDING_CONTENT.heroVariants.antiNoise.headline
    );
    // The embedded board renders real JobListingCards (Apply button per card).
    expect(screen.getAllByRole('link', { name: /apply/i }).length).toBeGreaterThanOrEqual(5);
    expect(screen.getByRole('link', { name: /browse all/i })).toBeInTheDocument();
  });

  it('category chips narrow the embedded board without any keyword-matching UI', async () => {
    renderBoard();
    const before = screen.getAllByRole('link', { name: /apply/i }).length;
    await userEvent.click(screen.getByRole('button', { name: 'Product Manager' }));
    const after = screen.getAllByRole('link', { name: /apply/i }).length;
    expect(after).toBeLessThan(before);
    // The keyword filter (saved keyword lists autocomplete) must NOT be here.
    expect(screen.queryByRole('combobox', { name: /keyword/i })).not.toBeInTheDocument();
  });

  it('sparse fixture degrades honestly: week-labeled rail, thinner board', () => {
    renderBoard(true);
    expect(screen.getByText('Fresh this week')).toBeInTheDocument();
    expect(screen.queryByText('Posted in the last 48 hours')).not.toBeInTheDocument();
  });

  it('renders the FAQ and footer link stubs', () => {
    renderBoard();
    expect(screen.getByText(LANDING_CONTENT.faq[0].question)).toBeInTheDocument();
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByText('Popular searches')).toBeInTheDocument();
  });
});
