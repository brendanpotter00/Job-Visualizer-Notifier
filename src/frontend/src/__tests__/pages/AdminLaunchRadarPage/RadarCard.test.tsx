import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import type {
  LaunchRadarCard,
  LaunchRadarSort,
  LaunchRadarStatus,
} from '../../../features/admin/launchRadarTypes';
import { RadarCard } from '../../../pages/AdminLaunchRadarPage/components/RadarCard';
import type { CardAction } from '../../../pages/AdminLaunchRadarPage/components/CardStatusLine';
import {
  makeAthennianCard,
  makeGhostCard,
  makeKestrelCard,
  makeKestrelWithPrCard,
  makeRaindropCard,
  OPEN_PR_URL,
  unblendedScores,
} from './fixtures';

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

function renderCard(
  card: LaunchRadarCard,
  onRequestDelete = vi.fn(),
  {
    sort,
    onLeave = vi.fn<(card: LaunchRadarCard, action: CardAction) => void>(),
  }: {
    sort?: LaunchRadarSort;
    onLeave?: Mock<(card: LaunchRadarCard, action: CardAction) => void>;
  } = {}
) {
  render(
    <Provider store={makeStore()}>
      <RadarCard card={card} sort={sort} onRequestDelete={onRequestDelete} onLeave={onLeave} />
    </Provider>
  );
  return { onRequestDelete, onLeave };
}

// The default MUI light palette (no ThemeProvider in these tests).
const PRIMARY = 'rgba(0, 0, 0, 0.87)';
const SECONDARY = 'rgba(0, 0, 0, 0.6)';
const DISABLED = 'rgba(0, 0, 0, 0.38)';

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

  it('renders the closed card from a fixture: name, site, one-liner, event, scores, status', () => {
    renderCard(makeRaindropCard());
    const card = screen.getByTestId('radar-card-1');

    expect(within(card).getByText('Raindrop AI')).toBeInTheDocument();
    const site = within(card).getByRole('link', { name: 'raindrop.ai' });
    expect(site).toHaveAttribute('href', 'https://www.raindrop.ai/');
    expect(site).toHaveAttribute('target', '_blank');
    expect(site).toHaveAttribute('rel', 'noopener noreferrer');
    expect(within(card).getByText('Monitoring for AI agents')).toBeInTheDocument();

    const event = within(card).getByTestId('radar-event-line');
    expect(event).toHaveTextContent('Series A $35M');
    expect(event).toHaveTextContent('Sep 17');
    expect(
      within(event).getByRole('link', { name: 'Announcement Raindrop AI' })
    ).toBeInTheDocument();

    expect(within(card).getByRole('group', { name: 'Talent score 49' })).toHaveTextContent('49');
    expect(within(card).getByRole('group', { name: 'VC score 55' })).toHaveTextContent('55');

    expect(within(card).getByText('Already tracked')).toBeInTheDocument();
    // "Already tracked" means the company is on the site: no board link beside it.
    expect(within(card).queryByRole('link', { name: /^Job board\b/ })).not.toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Save Raindrop AI' })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Archive Raindrop AI' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /^Unsave\b/ })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /^Restore\b/ })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: /^Delete\b/ })).not.toBeInTheDocument();
  });

  it('draws no logo tile: we never fetch logos', () => {
    for (const card of [makeRaindropCard(), makeGhostCard(), makeAthennianCard()]) {
      const { unmount } = render(
        <Provider store={makeStore()}>
          <RadarCard card={card} onRequestDelete={vi.fn()} />
        </Provider>
      );
      const el = screen.getByTestId(`radar-card-${card.id}`);
      // A letter tile is a box holding only the company's first letter.
      expect(within(el).queryByText(card.company.charAt(0))).not.toBeInTheDocument();
      expect(within(el).getByText(card.company)).toBeInTheDocument();
      unmount();
    }
  });

  describe('announcement link', () => {
    it('links the event line of the closed card to the triggering announcement, in a new tab', () => {
      renderCard(makeRaindropCard());
      expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');

      const event = screen.getByTestId('radar-event-line');
      const link = within(event).getByRole('link', { name: 'Announcement Raindrop AI' });
      expect(link).toHaveAttribute(
        'href',
        'https://www.techcrunch.com/2026/09/17/raindrop-series-a/'
      );
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
      expect(link).toHaveAttribute('title', 'techcrunch.com');
    });

    it('shows a month-only announcement as the month, not a made-up day', () => {
      const base = makeRaindropCard();
      renderCard(makeRaindropCard({ event: { ...base.event!, announcedAt: '2026-09' } }));
      const event = screen.getByTestId('radar-event-line');
      expect(event).toHaveTextContent('Sep 2026');
      expect(event).not.toHaveTextContent('Sep 1');
    });

    it('renders no link when the event has no source URL', () => {
      renderCard(makeGhostCard());
      expect(screen.getByTestId('radar-event-line')).toHaveTextContent('Seed $11M');
      expect(screen.queryByRole('link', { name: /^Announcement\b/ })).not.toBeInTheDocument();
    });

    it.each([
      'javascript:alert(1)',
      'JavaScript:alert(document.cookie)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'ftp://example.com/release.txt',
      'mailto:press@example.com',
      '/news/raindrop',
      'not a url',
    ])('renders no link for the non-http URL %s', (sourceUrl) => {
      const base = makeRaindropCard();
      renderCard(makeRaindropCard({ event: { ...base.event!, sourceUrl } }));
      expect(screen.getByTestId('radar-event-line')).toHaveTextContent('Series A $35M');
      expect(screen.queryByRole('link', { name: /^Announcement\b/ })).not.toBeInTheDocument();
    });

    it('accepts a plain http URL', () => {
      const base = makeRaindropCard();
      renderCard(
        makeRaindropCard({
          event: { ...base.event!, sourceUrl: 'http://www.globenewswire.com/news-release/1' },
        })
      );
      expect(screen.getByRole('link', { name: 'Announcement Raindrop AI' })).toHaveAttribute(
        'href',
        'http://www.globenewswire.com/news-release/1'
      );
    });

    it('opens the link without toggling the accordion', async () => {
      const user = userEvent.setup();
      renderCard(makeRaindropCard());

      await user.click(screen.getByRole('link', { name: 'Announcement Raindrop AI' }));
      expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByRole('region', { name: 'Team' })).not.toBeInTheDocument();
    });

    it('is not repeated in the footer of the open card', async () => {
      const user = userEvent.setup();
      renderCard(makeRaindropCard());
      await user.click(toggle('Raindrop AI'));

      expect(screen.getAllByRole('link', { name: 'Announcement Raindrop AI' })).toHaveLength(1);
      expect(screen.queryByRole('link', { name: 'techcrunch.com' })).not.toBeInTheDocument();
    });
  });

  it('shows a dash, never 0, when the talent score is null', () => {
    renderCard(makeGhostCard());
    const talent = screen.getByRole('group', { name: 'Talent: No score' });
    expect(talent).toHaveTextContent('–');
    expect(talent).not.toHaveTextContent('0');
    expect(within(talent).getByLabelText('No score')).toBeInTheDocument();
  });

  it('links "Job board" for an untracked company, and shows nothing when there is no board', () => {
    const { unmount } = render(
      <Provider store={makeStore()}>
        <RadarCard card={makeRaindropCard({ trackedCompanyId: null })} onRequestDelete={vi.fn()} />
      </Provider>
    );
    const board = screen.getByRole('link', { name: 'Job board Raindrop AI' });
    expect(board).toHaveAttribute('href', 'https://jobs.ashbyhq.com/Raindrop');
    expect(board).toHaveAttribute('target', '_blank');
    expect(board).toHaveAttribute('rel', 'noopener noreferrer');
    unmount();

    renderCard(
      makeRaindropCard({
        trackedCompanyId: null,
        careersUrl: null,
        ats: { ...makeRaindropCard().ats, boardUrl: null },
      })
    );
    expect(screen.queryByRole('link', { name: /^Job board\b/ })).not.toBeInTheDocument();
  });

  it('falls back to the careers page when the board URL is missing', () => {
    renderCard(
      makeRaindropCard({
        trackedCompanyId: null,
        ats: { ...makeRaindropCard().ats, boardUrl: null },
      })
    );
    expect(screen.getByRole('link', { name: 'Job board Raindrop AI' })).toHaveAttribute(
      'href',
      'https://www.raindrop.ai/careers'
    );
  });

  it('opens the job board without toggling the accordion', async () => {
    const user = userEvent.setup();
    renderCard(makeRaindropCard({ trackedCompanyId: null }));
    await user.click(screen.getByRole('link', { name: 'Job board Raindrop AI' }));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');
  });

  describe('link safety: only http(s) research URLs become links', () => {
    const UNSAFE = [
      'javascript:alert(1)',
      'JavaScript:alert(document.cookie)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      '/relative/path',
    ];

    it.each(UNSAFE)('renders the site as plain text for the website %s', (website) => {
      renderCard(makeRaindropCard({ website }));
      const card = screen.getByTestId('radar-card-1');
      expect(within(card).queryByRole('link', { name: 'raindrop.ai' })).not.toBeInTheDocument();
      expect(within(card).getByText('raindrop.ai')).toBeInTheDocument();
      expect(card.querySelector(`a[href="${website}"]`)).toBeNull();
    });

    it.each(UNSAFE)('renders no job board link for the board and careers URL %s', (url) => {
      renderCard(
        makeRaindropCard({
          trackedCompanyId: null,
          careersUrl: url,
          ats: { ...makeRaindropCard().ats, boardUrl: url },
        })
      );
      expect(screen.queryByRole('link', { name: /^Job board\b/ })).not.toBeInTheDocument();
      expect(screen.getByTestId('radar-card-1').querySelector(`a[href="${url}"]`)).toBeNull();
    });

    it('skips an unsafe board URL for a safe careers page', () => {
      renderCard(
        makeRaindropCard({
          trackedCompanyId: null,
          ats: { ...makeRaindropCard().ats, boardUrl: 'javascript:alert(1)' },
        })
      );
      expect(screen.getByRole('link', { name: 'Job board Raindrop AI' })).toHaveAttribute(
        'href',
        'https://www.raindrop.ai/careers'
      );
    });

    it('renders no unsafe href anywhere on an open card fed only unsafe URLs', async () => {
      const user = userEvent.setup();
      const bad = 'javascript:alert(1)';
      const data = 'data:text/html,<b>x</b>';
      const base = makeRaindropCard();
      renderCard(
        makeRaindropCard({
          trackedCompanyId: null,
          website: bad,
          careersUrl: data,
          event: { ...base.event!, sourceUrl: bad },
          ats: { ...base.ats, boardUrl: data, checkedUrl: bad },
          leaders: base.leaders.map((l) => ({ ...l, linkedinUrl: bad, profileUrl: data })),
          sources: [{ url: bad, title: 'x', field: null }],
        })
      );
      await user.click(toggle('Raindrop AI'));
      const card = screen.getByTestId('radar-card-1');
      expect(card.querySelectorAll('a[href]')).toHaveLength(0);
      // The text still renders; only the links are gone.
      expect(within(card).getByText('raindrop.ai')).toBeInTheDocument();
      expect(screen.getByTestId('radar-event-line')).toHaveTextContent('Series A $35M');
    });
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
    // Schools and employers only: prior exits are a leaders' signal, never a team line.
    expect(within(rest).queryByText(/exit|founder/i)).not.toBeInTheDocument();
    expect(within(rest).queryByText('No schools or employers listed')).not.toBeInTheDocument();

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
      screen.getByText('Talent 49: leaders 24 + team 25 (each out of 50)')
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('list', { name: 'Talent parts' }))
        .getAllByRole('listitem')
        .map((li) => li.textContent)
    ).toEqual([
      'Leaders 24: Priya Raman: top school (Berkeley); Priya Raman: prior exit (Ledgerline, acquired by Northwind)',
      'Team 25: the 1 school listed across 6 profiles is not a top school; 3 of the 3 employers listed across 6 profiles are top employers (+25)',
    ]);
    expect(
      screen.getByText('VC 55: CRV led (tier 2); Lightspeed joined (tier 1); round over $20M')
    ).toBeInTheDocument();

    // Footer: the board and the research cost (the announcement is on the event line)
    expect(screen.getByText('Ashby board, 9 open jobs')).toBeInTheDocument();
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
        scores: unblendedScores({ talent: null, vc: null, talentReasons: [], vcReasons: [] }),
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

  it('reads leaders from the brief as provenance, not as incomplete research', async () => {
    const user = userEvent.setup();
    const base = makeGhostCard();
    renderCard(
      makeGhostCard({
        leaders: makeRaindropCard().leaders,
        scores: { ...base.scores, talent: null },
        issues: ['leaders from the brief (FindAll found none); 2 company page(s) dropped'],
      })
    );
    await user.click(toggle('Ghost AI'));

    expect(screen.queryByRole('region', { name: 'Research incomplete' })).not.toBeInTheDocument();
    const team = screen.getByRole('region', { name: 'Team' });
    expect(within(team).getByText('Leaders from the company brief')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /why these scores/i }));
    expect(screen.getByText('Talent: no people data, so no score')).toBeInTheDocument();
    expect(screen.queryByText(/research incomplete/)).not.toBeInTheDocument();
  });

  describe('the Talent breakdown: one badge, both halves under "Why these scores"', () => {
    async function openWhy(card: LaunchRadarCard) {
      const user = userEvent.setup();
      renderCard(card);
      await user.click(toggle(card.company));
      await user.click(screen.getByRole('button', { name: /why these scores/i }));
    }
    const parts = () =>
      within(screen.getByRole('list', { name: 'Talent parts' }))
        .getAllByRole('listitem')
        .map((li) => li.textContent);
    const base = makeRaindropCard().scores;

    it('a leaders-only card: the leaders doubled, the team says why it is missing', async () => {
      const card = makeRaindropCard({
        scores: {
          ...base,
          talent: 38,
          talentLeaders: 19,
          talentTeam: null,
          talentBasis: 'leaders',
          talentTeamReasons: ['no public profiles found for the rest of the team'],
        },
      });
      await openWhy(card);
      expect(screen.getByRole('group', { name: 'Talent score 38' })).toHaveTextContent('38');
      expect(
        screen.getByText('Talent 38: leaders 19 of 50, doubled: no team data')
      ).toBeInTheDocument();
      expect(parts()).toEqual([
        'Leaders 19: Priya Raman: top school (Berkeley); Priya Raman: prior exit (Ledgerline, acquired by Northwind)',
        'Team: no public profiles found for the rest of the team',
      ]);
    });

    it('a team-only card: the team doubled, the leaders have no people data', async () => {
      const card = makeRaindropCard({
        scores: {
          ...base,
          talent: 24,
          talentLeaders: null,
          talentReasons: [],
          talentTeam: 12,
          talentBasis: 'team',
        },
      });
      await openWhy(card);
      expect(screen.getByRole('group', { name: 'Talent score 24' })).toHaveTextContent('24');
      expect(
        screen.getByText('Talent 24: team 12 of 50, doubled: no leader data')
      ).toBeInTheDocument();
      expect(parts()).toEqual([
        'Leaders: no people data',
        'Team 12: the 1 school listed across 6 profiles is not a top school; 3 of the 3 employers listed across 6 profiles are top employers (+25)',
      ]);
    });

    it('a legacy card (scored before the blend) keeps its one line and no parts', async () => {
      const card = makeRaindropCard({
        scores: unblendedScores({
          talent: 49,
          vc: 55,
          talentReasons: base.talentReasons,
          vcReasons: base.vcReasons,
        }),
      });
      await openWhy(card);
      expect(screen.getByRole('group', { name: 'Talent score 49' })).toHaveTextContent('49');
      expect(
        screen.getByText(
          'Talent 49: Priya Raman: top school (Berkeley); Priya Raman: prior exit (Ledgerline, acquired by Northwind)'
        )
      ).toBeInTheDocument();
      expect(screen.queryByRole('list', { name: 'Talent parts' })).not.toBeInTheDocument();
    });

    it('the card shows one Talent number, never the parts', () => {
      renderCard(makeRaindropCard());
      expect(screen.getAllByRole('group', { name: /^Talent/ })).toHaveLength(1);
      expect(screen.getByRole('group', { name: 'Talent score 49' })).toHaveTextContent('49');
      expect(screen.queryByText(/leaders 24/)).not.toBeInTheDocument();
    });
  });

  it('still lists the real gaps when a provenance note rides along', async () => {
    const user = userEvent.setup();
    renderCard(
      makeGhostCard({
        leaders: makeRaindropCard().leaders,
        issues: [
          'leaders from the brief (FindAll found none)',
          'team tally failed: task trun_2: failed (timeout)',
        ],
      })
    );
    await user.click(toggle('Ghost AI'));
    const issues = screen.getByRole('region', { name: 'Research incomplete' });
    expect(within(issues).getAllByRole('listitem')).toHaveLength(1);
    expect(
      within(issues).getByText('team tally failed: task trun_2: failed (timeout)')
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('region', { name: 'Team' })).getByText(
        'Leaders from the company brief'
      )
    ).toBeInTheDocument();
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
    renderCard(makeRaindropCard({ teamStats: { ...base.teamStats!, profilesFound: null } }));
    await user.click(toggle('Raindrop AI'));
    const rest = screen.getByRole('region', { name: 'Rest of team' });
    expect(within(rest).getByText('profile count unknown')).toBeInTheDocument();
    expect(within(rest).queryByText(/0 public profiles/)).not.toBeInTheDocument();
  });

  it('says so when the team tally lists no schools or employers', async () => {
    const user = userEvent.setup();
    const base = makeRaindropCard();
    // An older card may still carry the tally's prior-exit count; it is never shown.
    const legacyStats = {
      ...base.teamStats!,
      schools: [],
      priorEmployers: [],
      exFoundersWithExit: 1,
    };
    renderCard(makeRaindropCard({ teamStats: legacyStats }));
    await user.click(toggle('Raindrop AI'));
    const rest = screen.getByRole('region', { name: 'Rest of team' });
    expect(within(rest).getByText('6 public profiles')).toBeInTheDocument();
    expect(within(rest).getByText('No schools or employers listed')).toBeInTheDocument();
    expect(within(rest).queryByText(/exit|founder/i)).not.toBeInTheDocument();
  });

  it('saves on Save without toggling the accordion', async () => {
    const user = userEvent.setup();
    renderCard(makeRaindropCard());

    await user.click(screen.getByRole('button', { name: 'Save Raindrop AI' }));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.method).toBe('PATCH');
    expect(new URL(req.url).pathname).toBe('/api/admin/launch-radar/cards/1');
    expect(await req.json()).toEqual({ status: 'saved', from: 'new' });
  });

  it('shows the server reason when a save is refused', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ detail: 'card is archived; only a new card can move to saved' }),
        { status: 409, headers: { 'content-type': 'application/json' } }
      )
    );
    const user = userEvent.setup();
    renderCard(makeRaindropCard());
    await user.click(screen.getByRole('button', { name: 'Save Raindrop AI' }));
    expect(
      await screen.findByText('card is archived; only a new card can move to saved')
    ).toBeInTheDocument();
  });

  it.each([
    [makeRaindropCard, 'Save', 'Failed to save the card'],
    [makeRaindropCard, 'Archive', 'Failed to archive the card'],
    [makeKestrelCard, 'Unsave', 'Failed to unsave the card'],
    [makeAthennianCard, 'Restore', 'Failed to restore the card'],
  ])(
    'names the failed action when the error carries no reason (%#: %s)',
    async (make, button, text) => {
      fetchMock.mockResolvedValue(
        new Response(JSON.stringify({}), {
          status: 500,
          headers: { 'content-type': 'application/json' },
        })
      );
      const user = userEvent.setup();
      const card = make();
      renderCard(card);
      await user.click(screen.getByRole('button', { name: `${button} ${card.company}` }));
      expect(await screen.findByRole('alert')).toHaveTextContent(text);
    }
  );

  describe('saved card', () => {
    it('shows Unsave and Archive, and neither Save, Restore nor Delete', () => {
      renderCard(makeKestrelCard());
      const card = screen.getByTestId('radar-card-4');
      expect(within(card).getByRole('button', { name: 'Unsave Kestrel Labs' })).toBeInTheDocument();
      expect(
        within(card).getByRole('button', { name: 'Archive Kestrel Labs' })
      ).toBeInTheDocument();
      expect(within(card).queryByRole('button', { name: /^Save\b/ })).not.toBeInTheDocument();
      expect(within(card).queryByRole('button', { name: /^Restore\b/ })).not.toBeInTheDocument();
      expect(within(card).queryByRole('button', { name: /^Delete\b/ })).not.toBeInTheDocument();
      expect(within(card).getByRole('link', { name: 'Job board Kestrel Labs' })).toHaveAttribute(
        'href',
        'https://job-boards.greenhouse.io/kestrel'
      );
    });

    it.each([
      ['Unsave', 'new'],
      ['Archive', 'archived'],
    ])('%s sends PATCH status=%s without toggling the card', async (button, status) => {
      const user = userEvent.setup();
      renderCard(makeKestrelCard());

      await user.click(screen.getByRole('button', { name: `${button} Kestrel Labs` }));
      expect(toggle('Kestrel Labs')).toHaveAttribute('aria-expanded', 'false');

      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      const req = fetchMock.mock.calls[0][0] as Request;
      expect(req.method).toBe('PATCH');
      expect(new URL(req.url).pathname).toBe('/api/admin/launch-radar/cards/4');
      // `from`: the tab the card was clicked in, checked by the backend before it moves.
      expect(await req.json()).toEqual({ status, from: 'saved' });
    });
  });

  // The nightly loop opens an add-company PR for each Saved card; the card then
  // links it. Just the link: no status chip, no retry button (owner's call).
  describe('add-company PR link', () => {
    const PR_NAME = 'View PR #412 Kestrel Labs';

    it('links "View PR #412" on a Saved card with an open PR, beside the job board', () => {
      renderCard(makeKestrelWithPrCard());
      const card = screen.getByTestId('radar-card-4');
      const pr = within(card).getByRole('link', { name: PR_NAME });
      expect(pr).toHaveTextContent(/^View PR #412$/);
      expect(pr).toHaveAttribute('href', OPEN_PR_URL);
      expect(pr).toHaveAttribute('target', '_blank');
      expect(pr).toHaveAttribute('rel', 'noopener noreferrer');
      // Same left-hand unit as "Job board", after a middot.
      const left = within(card).getByRole('link', {
        name: 'Job board Kestrel Labs',
      }).parentElement!;
      expect(left).toContainElement(pr);
      expect(left).toHaveTextContent(/^Job board · View PR #412$/);
      // Nothing else: the actions are unchanged and no other PR control exists.
      const buttons = within(card)
        .getAllByRole('button')
        .map((b) => b.getAttribute('aria-label'));
      expect(buttons).toEqual([
        'Unsave Kestrel Labs',
        'Archive Kestrel Labs',
        'Show details for Kestrel Labs',
      ]);
      expect(within(card).getAllByRole('link', { name: /PR/ })).toHaveLength(1);
    });

    it('shows the link on any tab that has an open PR, and without a board beside it', () => {
      const { unmount } = render(
        <Provider store={makeStore()}>
          <RadarCard card={makeKestrelWithPrCard({ status: 'new' })} onRequestDelete={vi.fn()} />
        </Provider>
      );
      expect(screen.getByRole('link', { name: PR_NAME })).toBeInTheDocument();
      unmount();

      renderCard(
        makeKestrelWithPrCard({
          careersUrl: null,
          ats: { ...makeKestrelCard().ats, boardUrl: null },
        })
      );
      const pr = screen.getByRole('link', { name: PR_NAME });
      // No board link, so no leading middot either.
      expect(pr.parentElement).toHaveTextContent(/^View PR #412$/);
    });

    it('shows the link next to "Already tracked" and next to the archive date', () => {
      const { unmount } = render(
        <Provider store={makeStore()}>
          <RadarCard
            card={makeKestrelWithPrCard({ trackedCompanyId: 'kestrel' })}
            onRequestDelete={vi.fn()}
          />
        </Provider>
      );
      expect(screen.getByText('Already tracked').parentElement).toHaveTextContent(
        /^Already tracked · View PR #412$/
      );
      unmount();

      renderCard(makeKestrelWithPrCard({ status: 'archived', archivedAt: '2026-10-07T12:00:00Z' }));
      expect(screen.getByText('Archived Oct 7').parentElement).toHaveTextContent(
        /^Archived Oct 7 · View PR #412$/
      );
    });

    it.each([
      ['null', { prUrl: null, prNumber: null }],
      ['absent (a backend that predates the PR step)', { prUrl: undefined, prNumber: undefined }],
    ])('renders no PR link when the PR URL is %s', (_label, pr) => {
      renderCard(makeKestrelCard(pr));
      const card = screen.getByTestId('radar-card-4');
      expect(within(card).queryByRole('link', { name: /^View PR\b/ })).not.toBeInTheDocument();
      expect(within(card).queryByText(/PR/)).not.toBeInTheDocument();
      expect(
        within(card).getByRole('link', { name: 'Job board Kestrel Labs' }).parentElement
      ).toHaveTextContent(/^Job board$/);
    });

    it.each([
      'javascript:alert(1)',
      'data:text/html,<b>x</b>',
      'http://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/412',
      'https://github.com/someone-else/Job-Visualizer-Notifier/pull/412',
      'https://github.com.evil.example/brendanpotter00/Job-Visualizer-Notifier/pull/412',
      'https://github.com/brendanpotter00/Job-Visualizer-Notifier/issues/412',
      'https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/412#x',
      'https://evil.example/pull/412',
    ])('renders no PR link for the URL %s', (prUrl) => {
      renderCard(makeKestrelWithPrCard({ prUrl }));
      const card = screen.getByTestId('radar-card-4');
      expect(within(card).queryByRole('link', { name: /^View PR\b/ })).not.toBeInTheDocument();
      expect(card.querySelector(`a[href="${prUrl}"]`)).toBeNull();
    });

    it('opens the PR without toggling the card', async () => {
      const user = userEvent.setup();
      renderCard(makeKestrelWithPrCard());
      await user.click(screen.getByRole('link', { name: PR_NAME }));
      expect(toggle('Kestrel Labs')).toHaveAttribute('aria-expanded', 'false');
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  it('archives on Archive without toggling the accordion', async () => {
    const user = userEvent.setup();
    renderCard(makeRaindropCard());

    await user.click(screen.getByRole('button', { name: 'Archive Raindrop AI' }));
    expect(toggle('Raindrop AI')).toHaveAttribute('aria-expanded', 'false');

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.method).toBe('PATCH');
    expect(new URL(req.url).pathname).toBe('/api/admin/launch-radar/cards/1');
    expect(await req.json()).toEqual({ status: 'archived', from: 'new' });
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
    await user.click(screen.getByRole('button', { name: 'Archive Raindrop AI' }));
    expect(await screen.findByText('card already archived')).toBeInTheDocument();
  });

  describe('archived card', () => {
    it('shows the archive date, Restore and Delete', async () => {
      const user = userEvent.setup();
      const { onRequestDelete } = renderCard(makeAthennianCard());

      // The date replaces the job board link on the left of the status line.
      expect(screen.getByText('Archived Oct 7')).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /^Job board\b/ })).not.toBeInTheDocument();
      for (const label of ['Save', 'Unsave', 'Archive']) {
        expect(
          screen.queryByRole('button', { name: new RegExp(`^${label}\\b`) })
        ).not.toBeInTheDocument();
      }
      const event = screen.getByTestId('radar-event-line');
      expect(event).toHaveTextContent('Launch');
      expect(event).toHaveTextContent('Oct 6');

      await user.click(screen.getByRole('button', { name: 'Delete Athennian' }));
      expect(onRequestDelete).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }));
      expect(toggle('Athennian')).toHaveAttribute('aria-expanded', 'false');
      expect(fetchMock).not.toHaveBeenCalled();

      await user.click(screen.getByRole('button', { name: 'Restore Athennian' }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      const req = fetchMock.mock.calls[0][0] as Request;
      expect(req.method).toBe('PATCH');
      expect(await req.json()).toEqual({ status: 'new', from: 'archived' });
    });

    it('warns when the leaders came back without any background', async () => {
      const user = userEvent.setup();
      renderCard(makeAthennianCard());
      await user.click(toggle('Athennian'));
      expect(
        screen.getByText('No background data came back for these leaders')
      ).toBeInTheDocument();
      expect(screen.getByText('Other board, not verified')).toBeInTheDocument();
    });
  });

  describe('accessible names', () => {
    it('names every action and link after its company, so no two cards share one', () => {
      render(
        <Provider store={makeStore()}>
          <RadarCard
            card={makeRaindropCard({ trackedCompanyId: null })}
            onRequestDelete={vi.fn()}
          />
          <RadarCard card={makeGhostCard()} onRequestDelete={vi.fn()} />
          <RadarCard card={makeKestrelCard()} onRequestDelete={vi.fn()} />
          <RadarCard card={makeAthennianCard()} onRequestDelete={vi.fn()} />
        </Provider>
      );
      const names = (role: 'button' | 'link') =>
        screen.getAllByRole(role).map((el) => el.getAttribute('aria-label') ?? el.textContent);
      for (const role of ['button', 'link'] as const) {
        const all = names(role);
        expect(new Set(all).size).toBe(all.length);
      }
      for (const name of [
        'Save Raindrop AI',
        'Archive Raindrop AI',
        'Save Ghost AI',
        'Unsave Kestrel Labs',
        'Archive Kestrel Labs',
        'Restore Athennian',
        'Delete Athennian',
      ]) {
        expect(screen.getByRole('button', { name })).toBeInTheDocument();
      }
      for (const name of [
        'Job board Raindrop AI',
        'Job board Ghost AI',
        'Announcement Raindrop AI',
        'Announcement Athennian',
      ]) {
        expect(screen.getByRole('link', { name })).toBeInTheDocument();
      }
    });

    it('keeps the visible label at the start of each accessible name', () => {
      renderCard(makeRaindropCard({ trackedCompanyId: null }));
      for (const label of ['Save', 'Archive']) {
        const button = screen.getByRole('button', { name: `${label} Raindrop AI` });
        expect(button).toHaveTextContent(label);
      }
      expect(screen.getByRole('link', { name: 'Job board Raindrop AI' })).toHaveTextContent(
        'Job board'
      );
    });
  });

  it('renders no actions, rather than crashing, for a status this build does not know', () => {
    renderCard(makeRaindropCard({ status: 'starred' as LaunchRadarStatus }));
    const card = screen.getByTestId('radar-card-1');
    expect(within(card).getByText('Raindrop AI')).toBeInTheDocument();
    for (const label of ['Save', 'Unsave', 'Archive', 'Restore', 'Delete']) {
      expect(within(card).queryByRole('button', { name: new RegExp(`^${label}\\b`) })).toBeNull();
    }
    expect(toggle('Raindrop AI')).toBeInTheDocument();
  });

  describe('after a successful move', () => {
    it('keeps the actions disabled (the card is leaving) and reports the move', async () => {
      const user = userEvent.setup();
      const card = makeRaindropCard();
      const { onLeave } = renderCard(card);

      await user.click(screen.getByRole('button', { name: 'Save Raindrop AI' }));

      await waitFor(() => expect(onLeave).toHaveBeenCalledWith(card, 'save'));
      // The list has not refetched yet: no second press may reach the server.
      expect(screen.getByRole('button', { name: 'Save Raindrop AI' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Archive Raindrop AI' })).toBeDisabled();
      // Even a click that reaches it (MUI also sets pointer-events: none) sends nothing.
      await userEvent
        .setup({ pointerEventsCheck: 0 })
        .click(screen.getByRole('button', { name: 'Archive Raindrop AI' }));
      expect(fetchMock).toHaveBeenCalledTimes(1);
      // The details toggle still works.
      expect(toggle('Raindrop AI')).toBeEnabled();
    });

    it('re-enables the actions and reports nothing when the move is refused', async () => {
      fetchMock.mockResolvedValue(
        new Response(JSON.stringify({ detail: 'card is archived' }), {
          status: 409,
          headers: { 'content-type': 'application/json' },
        })
      );
      const user = userEvent.setup();
      const { onLeave } = renderCard(makeRaindropCard());

      await user.click(screen.getByRole('button', { name: 'Save Raindrop AI' }));

      expect(await screen.findByText('card is archived')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Save Raindrop AI' })).toBeEnabled();
      expect(onLeave).not.toHaveBeenCalled();
    });
  });

  describe('score emphasis follows the sort', () => {
    const numeral = (name: string) =>
      screen.getByRole('group', { name }).firstElementChild as HTMLElement;

    it.each([
      ['talent', 'strong', 'muted'],
      ['vc', 'muted', 'strong'],
      ['added', 'normal', 'normal'],
      // No sort given: the page default, Talent.
      [undefined, 'strong', 'muted'],
    ] as const)('sort=%s: Talent %s, VC %s', (sort, talent, vc) => {
      renderCard(makeRaindropCard(), vi.fn(), { sort });
      expect(screen.getByRole('group', { name: 'Talent score 49' })).toHaveAttribute(
        'data-emphasis',
        talent
      );
      expect(screen.getByRole('group', { name: 'VC score 55' })).toHaveAttribute(
        'data-emphasis',
        vc
      );
      const color = { strong: PRIMARY, normal: PRIMARY, muted: SECONDARY };
      expect(numeral('Talent score 49')).toHaveStyle({ color: color[talent] });
      expect(numeral('VC score 55')).toHaveStyle({ color: color[vc] });
    });

    it('keeps an unscored numeral greyed out whatever the sort', () => {
      renderCard(makeGhostCard(), vi.fn(), { sort: 'talent' });
      expect(numeral('Talent: No score')).toHaveStyle({ color: DISABLED });
      expect(numeral('Talent: No score')).toHaveTextContent('–');
      expect(numeral('VC score 65')).toHaveStyle({ color: SECONDARY });
    });
  });

  // A phone-width card used to break inside phrases ("Series / A $116 /
  // million", "Job / board"). Each piece is now kept whole and the pieces wrap
  // as units; jsdom has no layout, so this pins the styles that guarantee it.
  describe('narrow card: phrases wrap whole, never mid-label', () => {
    it('keeps the round and amount, the date and the link each on one line', () => {
      renderCard(makeRaindropCard());
      const event = screen.getByTestId('radar-event-line');
      expect(event).toHaveStyle({ display: 'flex', flexWrap: 'wrap' });
      const [round, date, link] = Array.from(event.children);
      expect(round).toHaveTextContent(/^Series A \$35M$/);
      expect(date).toHaveTextContent(/^Sep 17$/);
      expect(link).toHaveAccessibleName('Announcement Raindrop AI');
      for (const piece of [round, date, link]) {
        expect(piece).toHaveStyle({ whiteSpace: 'nowrap' });
      }
    });

    it('wraps the status line as units: "Already tracked" whole, the actions together', () => {
      renderCard(makeRaindropCard());
      const left = screen.getByText('Already tracked').parentElement!;
      expect(left).toHaveStyle({ whiteSpace: 'nowrap' });
      const line = left.parentElement!;
      expect(line).toHaveStyle({ display: 'flex', flexWrap: 'wrap' });
      const actions = screen.getByRole('button', { name: 'Save Raindrop AI' }).parentElement!;
      expect(line).toContainElement(actions);
      expect(actions).toContainElement(screen.getByRole('button', { name: 'Archive Raindrop AI' }));
      expect(actions).toHaveStyle({ flexShrink: '0' });
    });
  });
});
