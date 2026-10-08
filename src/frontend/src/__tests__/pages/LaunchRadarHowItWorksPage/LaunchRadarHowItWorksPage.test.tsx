import { describe, it, expect } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LaunchRadarHowItWorksPage } from '../../../pages/LaunchRadarHowItWorksPage/LaunchRadarHowItWorksPage';

function box(name: RegExp) {
  return screen.getByRole('button', { name });
}

function panel() {
  return screen.getByRole('complementary', { name: /./ });
}

describe('LaunchRadarHowItWorksPage', () => {
  it('shows the goal, both ways in, and every step as a box', () => {
    render(<LaunchRadarHowItWorksPage />);
    expect(
      screen.getByRole('heading', { level: 1, name: 'How Launch Radar works' })
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Before' })).toBeInTheDocument();
    expect(screen.getByText(/I scroll X or LinkedIn/)).toBeInTheDocument();
    expect(screen.getByText('Daily Claude Code')).toBeInTheDocument();
    expect(screen.getByText('Backfill')).toBeInTheDocument();
    for (const name of [
      /Find new startups/,
      /Find past startups/,
      /Get each startup's announcement/,
      /Find the website, if missing/,
      /Find the leaders/,
      /Research the company/,
      /Tally the rest of the team/,
      /Research each leader/,
      /Score and post the card/,
    ]) {
      expect(box(name)).toHaveAttribute('aria-expanded', 'false');
    }
  });

  it('opens a box in the side panel with its facts and request body', async () => {
    const user = userEvent.setup();
    render(<LaunchRadarHowItWorksPage />);
    await user.click(box(/Find past startups/));

    expect(box(/Find past startups/)).toHaveAttribute('aria-expanded', 'true');
    const side = panel();
    expect(
      within(side).getByRole('heading', { level: 2, name: 'Find past startups' })
    ).toBeInTheDocument();
    expect(within(side).getByText('Generator')).toBeInTheDocument();
    expect(within(side).getByText('$0.25 + $0.03 / match')).toBeInTheDocument();
    expect(within(side).getByText('~12 min')).toBeInTheDocument();
    expect(within(side).getByText('"entity_type"')).toBeInTheDocument();
    expect(within(side).getByText('"companies"')).toBeInTheDocument();
  });

  it('switches to another box, and a second click on the same box closes the panel', async () => {
    const user = userEvent.setup();
    render(<LaunchRadarHowItWorksPage />);
    await user.click(box(/Find new startups/));
    await user.click(box(/Tally the rest of the team/));
    expect(box(/Find new startups/)).toHaveAttribute('aria-expanded', 'false');
    expect(within(panel()).getByText('pro')).toBeInTheDocument();

    await user.click(box(/Tally the rest of the team/));
    expect(box(/Tally the rest of the team/)).toHaveAttribute('aria-expanded', 'false');
  });

  it('explains the scoring on the free last step', async () => {
    const user = userEvent.setup();
    render(<LaunchRadarHowItWorksPage />);
    await user.click(box(/Score and post the card/));
    const side = panel();
    expect(within(side).getByText('A prior exit (acquired or IPO)')).toBeInTheDocument();
    expect(
      within(side).getByText('Founding a company scores nothing. Only an exit counts.')
    ).toBeInTheDocument();
    expect(within(side).getByRole('heading', { name: 'Example: Lightfield' })).toBeInTheDocument();
  });

  it('closes on Escape and on Close, and gives focus back to the box', async () => {
    const user = userEvent.setup();
    render(<LaunchRadarHowItWorksPage />);
    await user.click(box(/Research the company/));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus());
    await user.keyboard('{Escape}');
    expect(box(/Research the company/)).toHaveAttribute('aria-expanded', 'false');
    expect(box(/Research the company/)).toHaveFocus();

    await user.click(box(/Find the leaders/));
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(box(/Find the leaders/)).toHaveAttribute('aria-expanded', 'false');
  });

  it('breaks the cost down by step', async () => {
    const user = userEvent.setup();
    render(<LaunchRadarHowItWorksPage />);
    await user.click(screen.getByRole('button', { name: 'Cost' }));
    expect(await screen.findByText('About $0.28 per company')).toBeVisible();
    expect(
      screen.getByRole('img', { name: /Cost per company by step: Find the leaders \$0\.10/ })
    ).toBeInTheDocument();
    expect(screen.getByText('$0.025')).toBeInTheDocument();
    expect(screen.getByText(/about \$26/)).toBeInTheDocument();
  });

  it('compares the cost with an Opus agent in its own section of the cost accordion', async () => {
    const user = userEvent.setup();
    render(<LaunchRadarHowItWorksPage />);
    await user.click(screen.getByRole('button', { name: 'Cost' }));
    expect(await screen.findByText('An Opus agent: about $1.90 per company')).toBeVisible();
    expect(screen.getByText('Opus agent')).toBeInTheDocument();
    expect(screen.getByText('~$1.90')).toBeInTheDocument();
    expect(screen.getByText(/23 searches and 36 page fetches/)).toBeInTheDocument();
    expect(screen.getByText(/Opyn's sale was not the founders' exit/)).toBeInTheDocument();
    expect(screen.getByText(/1 usable team profile to Parallel's 6/)).toBeInTheDocument();
  });
});
