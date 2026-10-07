import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import type { LaunchRadarCard } from '../../../features/admin/launchRadarTypes';
import { RadarCard } from '../../../pages/AdminLaunchRadarPage/components/RadarCard';
import { makeAthennianCard, makeGhostCard, makeRaindropCard } from './fixtures';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// ones. Same shim as the other admin page tests.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string' && input.startsWith('/')) {
      super(`http://localhost${input}`, init);
    } else {
      super(input, init);
    }
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

function makeStore() {
  return configureStore({
    reducer: { [adminApi.reducerPath]: adminApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull: () => Promise.resolve('test-token') } },
      }).concat(adminApi.middleware),
  });
}

function renderCard(card: LaunchRadarCard, onRequestDelete = vi.fn()) {
  render(
    <Provider store={makeStore()}>
      <RadarCard card={card} onRequestDelete={onRequestDelete} />
    </Provider>
  );
  return { onRequestDelete };
}

/**
 * The card's accessible toggle (the chevron in the status line). Its name
 * flips between "Show details for X" and "Hide details for X".
 */
function toggle(company: string): HTMLElement {
  return screen.getByRole('button', { name: new RegExp(`details for ${company}$`) });
}

describe('RadarCard', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(makeRaindropCard({ status: 'archived' })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    );
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('renders the closed card from a fixture: logo letter, name, site, one-liner, event, scores, status', () => {
    renderCard(makeRaindropCard());
    const card = screen.getByTestId('radar-card-1');

    expect(within(card).getByText('R')).toBeInTheDocument();
    expect(within(card).getByText('Raindrop AI')).toBeInTheDocument();
    const site = within(card).getByRole('link', { name: 'raindrop.ai' });
    expect(site).toHaveAttribute('href', 'https://www.raindrop.ai');
    expect(site).toHaveAttribute('target', '_blank');
    expect(site).toHaveAttribute('rel', 'noopener noreferrer');
    expect(within(card).getByText('Monitoring for AI agents')).toBeInTheDocument();

    const event = within(card).getByTestId('radar-event-line');
    expect(event).toHaveTextContent('Series A $35M');
    expect(event).toHaveTextContent('Sep 17');

    expect(within(card).getByRole('group', { name: 'Talent score 49' })).toHaveTextContent('49');
    expect(within(card).getByRole('group', { name: 'VC score 55' })).toHaveTextContent('55');

    expect(within(card).getByText('Already tracked')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Archive' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  });

  it('shows a dash, never 0, when the talent score is null', () => {
    renderCard(makeGhostCard());
    const talent = screen.getByRole('group', { name: 'Talent: No score' });
    expect(talent).toHaveTextContent('–');
    expect(talent).not.toHaveTextContent('0');
    expect(within(talent).getByLabelText('No score')).toBeInTheDocument();
  });

  it('links the add-company PR when one is ready', () => {
    renderCard(makeGhostCard());
    expect(screen.getByRole('link', { name: 'Add-company PR ready' })).toHaveAttribute(
      'href',
      'https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/400'
    );
  });

  it('shows "No PR" with the job board link, and omits the link when there is no board', () => {
    const { unmount } = render(
      <Provider store={makeStore()}>
        <RadarCard card={makeRaindropCard({ trackedCompanyId: null })} onRequestDelete={vi.fn()} />
      </Provider>
    );
    expect(screen.getByText(/No PR/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open job board' })).toHaveAttribute(
      'href',
      'https://jobs.ashbyhq.com/Raindrop'
    );
    unmount();

    renderCard(
      makeRaindropCard({
        trackedCompanyId: null,
        careersUrl: null,
        ats: { ...makeRaindropCard().ats, boardUrl: null },
      })
    );
    expect(screen.getByText(/No PR/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open job board' })).not.toBeInTheDocument();
  });

  it('opens the accordion body on a click and shows every section', async () => {
    const user = userEvent.setup();
    renderCard(makeRaindropCard());

    expect(screen.queryByText('Rest of team')).not.toBeInTheDocument();
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');
    expect(toggle('Raindrop AI')).toHaveAccessibleName('Show details for Raindrop AI');
    await user.click(toggle('Raindrop AI'));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'true');
    expect(toggle('Raindrop AI')).toHaveAccessibleName('Hide details for Raindrop AI');

    // Team
    const team = screen.getByRole('region', { name: 'Team' });
    expect(within(team).getByText('Priya Raman')).toBeInTheDocument();
    expect(within(team).getByText('CEO')).toBeInTheDocument();
    expect(
      within(team).getByText('Berkeley CS. Co-founded Ledgerline, acquired by Northwind')
    ).toBeInTheDocument();
    expect(within(team).getByText('Sam Rivera')).toBeInTheDocument();

    // Rest of team (the team tally)
    const rest = screen.getByRole('region', { name: 'Rest of team' });
    expect(within(rest).getByText('6 public profiles')).toBeInTheDocument();
    expect(within(rest).getByText('Previously at Amazon (2) and Twitter')).toBeInTheDocument();
    expect(within(rest).getByText('2 schools: UC Davis and UCSB')).toBeInTheDocument();
    expect(within(rest).getByText('No prior exits found')).toBeInTheDocument();

    // Funding
    const funding = screen.getByRole('region', { name: 'Funding' });
    expect(within(funding).getByText('$50M total')).toBeInTheDocument();
    expect(funding).toHaveTextContent(
      'Series A $35M, Sep 2026. Led by CRV, with Lightspeed and Y Combinator'
    );
    expect(funding).toHaveTextContent(
      'Seed $15M. Lightspeed, Figma Ventures, Vercel Ventures and 1 more'
    );

    // Highlights: at most 3
    const highlights = screen.getByRole('region', { name: 'Highlights' });
    expect(within(highlights).getAllByRole('listitem')).toHaveLength(3);
    expect(within(highlights).queryByText('A fourth fact the card never shows')).toBeNull();

    // Why these scores: collapsed until asked
    const why = screen.getByRole('button', { name: /why these scores/i });
    expect(why).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/^Talent 49:/)).not.toBeInTheDocument();
    await user.click(why);
    expect(why).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.getByText(
        'Talent 49: Priya Raman: top school (Berkeley); Priya Raman: prior exit (Ledgerline, acquired by Northwind)'
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText('VC 55: CRV led (tier 2); Lightspeed joined (tier 1); round over $20M')
    ).toBeInTheDocument();

    // Footer
    expect(screen.getByText('Ashby board, 9 open jobs')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'techcrunch.com' })).toHaveAttribute(
      'href',
      'https://www.techcrunch.com/2026/09/17/raindrop-series-a/'
    );
    expect(screen.getByText('$0.30 research')).toBeInTheDocument();

    // A second click closes it again.
    await user.click(toggle('Raindrop AI'));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Rest of team')).not.toBeInTheDocument();
  });

  it('also opens on a click anywhere on the card header, but not on its links', async () => {
    const user = userEvent.setup();
    renderCard(makeRaindropCard());

    await user.click(screen.getByRole('link', { name: 'raindrop.ai' }));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');

    await user.click(screen.getByText('Monitoring for AI agents'));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('region', { name: 'Rest of team' })).toBeInTheDocument();
  });

  it('nests no button or link inside another button (valid, accessible markup)', () => {
    renderCard(makeGhostCard());
    for (const button of document.querySelectorAll('button')) {
      expect(button.querySelector('button, a')).toBeNull();
    }
  });

  it('explains a card with no people data', async () => {
    const user = userEvent.setup();
    renderCard(makeGhostCard());
    await user.click(toggle('Ghost AI'));

    const team = screen.getByRole('region', { name: 'Team' });
    expect(within(team).getByText('No leaders confirmed.')).toBeInTheDocument();
    expect(
      within(team).getByText(/The people search returned company pages\./)
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Rest of team' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /why these scores/i }));
    expect(screen.getByText('Talent: no people data, so no score')).toBeInTheDocument();
    expect(screen.getByText('Ashby board, 1 open job')).toBeInTheDocument();
  });

  it('says the research is incomplete when a step failed, instead of "no data"', async () => {
    const user = userEvent.setup();
    renderCard(
      makeGhostCard({
        scores: { talent: null, vc: null, talentReasons: [], vcReasons: [] },
        issues: ['brief failed: task trun_1: failed (processor error)', 'no leaders confirmed'],
      })
    );
    await user.click(toggle('Ghost AI'));

    const issues = screen.getByRole('region', { name: 'Research incomplete' });
    expect(
      within(issues).getByText('brief failed: task trun_1: failed (processor error)')
    ).toBeInTheDocument();
    expect(within(issues).getByText('no leaders confirmed')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /why these scores/i }));
    expect(screen.getByText('Talent: not scored, research incomplete')).toBeInTheDocument();
    expect(screen.getByText('VC: not scored, research incomplete')).toBeInTheDocument();
    expect(screen.queryByText(/no people data/)).not.toBeInTheDocument();
  });

  it('shows no issues block when research was complete', async () => {
    const user = userEvent.setup();
    renderCard(makeRaindropCard());
    await user.click(toggle('Raindrop AI'));
    expect(screen.queryByRole('region', { name: 'Research incomplete' })).not.toBeInTheDocument();
  });

  it('renders unknown team counts as unknown, never as zero', async () => {
    const user = userEvent.setup();
    const base = makeRaindropCard();
    renderCard(
      makeRaindropCard({
        teamStats: { ...base.teamStats!, profilesFound: null, exFoundersWithExit: null },
      })
    );
    await user.click(toggle('Raindrop AI'));
    const rest = screen.getByRole('region', { name: 'Rest of team' });
    expect(within(rest).getByText('profile count unknown')).toBeInTheDocument();
    expect(within(rest).getByText('Prior exits unknown')).toBeInTheDocument();
    expect(within(rest).queryByText('No prior exits found')).not.toBeInTheDocument();
    expect(within(rest).queryByText(/0 public profiles/)).not.toBeInTheDocument();
  });

  it('archives on Archive without toggling the accordion', async () => {
    const user = userEvent.setup();
    renderCard(makeRaindropCard());

    await user.click(screen.getByRole('button', { name: 'Archive' }));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.method).toBe('PATCH');
    expect(new URL(req.url).pathname).toBe('/api/admin/launch-radar/cards/1');
    expect(await req.json()).toEqual({ status: 'archived' });
  });

  it('shows an inline error when the archive request fails', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'card already archived' }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      })
    );
    const user = userEvent.setup();
    renderCard(makeRaindropCard());
    await user.click(screen.getByRole('button', { name: 'Archive' }));
    expect(await screen.findByText('card already archived')).toBeInTheDocument();
  });

  describe('archived card', () => {
    it('shows the archive date, Restore and Delete', async () => {
      const user = userEvent.setup();
      const { onRequestDelete } = renderCard(makeAthennianCard());

      expect(screen.getByText('Archived Oct 7')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument();
      const event = screen.getByTestId('radar-event-line');
      expect(event).toHaveTextContent('Launch');
      expect(event).toHaveTextContent('Oct 6');

      await user.click(screen.getByRole('button', { name: 'Delete' }));
      expect(onRequestDelete).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }));
      expect(toggle('Athennian')).toHaveAttribute('aria-expanded', 'false');
      expect(fetchMock).not.toHaveBeenCalled();

      await user.click(screen.getByRole('button', { name: 'Restore' }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      const req = fetchMock.mock.calls[0][0] as Request;
      expect(req.method).toBe('PATCH');
      expect(await req.json()).toEqual({ status: 'new' });
    });

    it('warns when the leaders came back without any background', async () => {
      const user = userEvent.setup();
      renderCard(makeAthennianCard());
      await user.click(toggle('Athennian'));
      expect(
        screen.getByText('No background data came back for these leaders')
      ).toBeInTheDocument();
      expect(screen.getByText('Other board, no PR')).toBeInTheDocument();
    });
  });
});
