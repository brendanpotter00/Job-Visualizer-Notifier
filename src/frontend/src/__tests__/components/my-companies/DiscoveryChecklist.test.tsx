import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { DiscoveryChecklist } from '../../../components/my-companies/DiscoveryChecklist';
import type {
  DiscoveryProgress,
  DiscoveryStep,
  UserCompany,
} from '../../../features/userCompanies/userCompaniesApi';

/**
 * The 4-step discovery checklist that replaced the "Setting up…" spinner.
 *
 * The properties under test are the ones that make it worth building at all:
 *
 * - the four rungs are named in the user's words — opening the page → reading jobs →
 *   building web scraper → ready to track — in that order, in every state;
 * - a refusal NAMES the step that stopped and carries WHY on it, then offers the one
 *   thing that changes the answer — never a bare "retry" (discovery is deterministic:
 *   the same URL reaches the same refusal, so a retry spends a browser session to
 *   reproduce an answer the user already has);
 * - a step that SUCCEEDED shows a tick and nothing else. Its `result` is engine
 *   telemetry ("recorded 14 JSON request(s)") and putting it under every rung buried
 *   the four words that matter in four lines of jargon; and
 * - with no live-view URL — the DEFAULT, because our own Chromium has no hosted view —
 *   there is no iframe, no toggle, and nothing missing from the layout.
 *
 * The component is presentational and flag-free (its caller owns the flag), so these
 * render it directly. The flag-off render is asserted in `MyCompaniesList.test.tsx`,
 * where the gate actually lives.
 */

function step(
  key: DiscoveryStep['key'],
  status: DiscoveryStep['status'],
  result: string | null = null,
): DiscoveryStep {
  return { key, status, result };
}

function progress(overrides: Partial<DiscoveryProgress> = {}): DiscoveryProgress {
  return {
    steps: [
      step('open_page', 'pending'),
      step('find_feed', 'pending'),
      step('verify_read', 'pending'),
      step('ready', 'pending'),
    ],
    outcome: 'running',
    liveViewUrl: null,
    updatedAt: '2026-08-20T12:00:00Z',
    ...overrides,
  };
}

function company(
  healthState: string,
  discovery: DiscoveryProgress | null,
  overrides: Partial<UserCompany> = {},
): UserCompany {
  return {
    id: 'u-discover01',
    displayName: 'Acme',
    ats: 'discovered',
    boardToken: 'https://careers.acme.example/jobs',
    sourceId: 'custom:u-discover01',
    healthState,
    openJobCount: 0,
    lastSuccessAt: null,
    trackingStartedAt: null,
    discovery,
    ...overrides,
  };
}

const RUNNING = progress({
  steps: [
    step('open_page', 'done', 'opened careers.acme.example — recorded 14 JSON request(s)'),
    step('find_feed', 'active'),
    step('verify_read', 'pending'),
    step('ready', 'pending'),
  ],
});

const TRACKING = progress({
  outcome: 'tracking',
  steps: [
    step('open_page', 'done', 'opened careers.acme.example — recorded 14 JSON request(s)'),
    step('find_feed', 'done', 'found 3 candidate feed(s)'),
    step('verify_read', 'done', 'read 90 job(s)'),
    step('ready', 'done', "reading the board's own feed directly — no browser needed"),
  ],
});

const REFUSED = progress({
  outcome: 'refused',
  steps: [
    step('open_page', 'done', 'opened careers.acme.example — recorded 14 JSON request(s)'),
    step('find_feed', 'done', 'found 3 candidate feed(s)'),
    step(
      'verify_read',
      'failed',
      'only 1 of the 12 job(s) the browser saw came back from the replay',
    ),
    step('ready', 'pending'),
  ],
});

describe('DiscoveryChecklist', () => {
  it('names all four steps, in the user\'s words, in order, whatever the state', () => {
    renderWithProviders(<DiscoveryChecklist company={company('discovering', RUNNING)} />);

    const list = screen.getByTestId('discovery-checklist');
    expect(within(list).getByText('Opening the page')).toBeInTheDocument();
    expect(within(list).getByText('Reading jobs')).toBeInTheDocument();
    expect(within(list).getByText('Building web scraper')).toBeInTheDocument();
    expect(within(list).getByText('Ready to track')).toBeInTheDocument();
  });

  it('shows a tick and nothing else on a step that succeeded', () => {
    // The engine's own words for a finished step — "recorded 14 JSON request(s)",
    // "found 3 candidate feed(s)" — describe our pipeline, not anything the reader can
    // do, and one under every rung turned a 4-line list into an 8-line one.
    renderWithProviders(<DiscoveryChecklist company={company('unverified', TRACKING)} />);

    expect(screen.getByText('Reading jobs')).toBeInTheDocument();
    expect(screen.queryByTestId('discovery-result-open_page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-result-find_feed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-result-verify_read')).not.toBeInTheDocument();
    expect(screen.queryByText(/JSON request/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/candidate feed/i)).not.toBeInTheDocument();
  });

  it('renders a mid-run board as still working', () => {
    renderWithProviders(<DiscoveryChecklist company={company('discovering', RUNNING)} />);

    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute(
      'data-outcome',
      'running',
    );
    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(/setting up acme/i);
    // Nothing to act on yet — the alternatives belong to a refusal.
    expect(screen.queryByTestId('discovery-next-actions')).not.toBeInTheDocument();
  });

  it('renders success as "we can read this board", and says it once', () => {
    // No job preview ("A few of the jobs we found") and no ✓/✕ summary chain: both
    // restated, in a second form, what the ticked rungs beside them already say.
    renderWithProviders(<DiscoveryChecklist company={company('unverified', TRACKING)} />);

    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(
      /we can read acme's board/i,
    );
    expect(screen.queryByTestId('discovery-job-preview')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-summary')).not.toBeInTheDocument();
    expect(screen.queryByText(/jobs we found/i)).not.toBeInTheDocument();
  });

  it('frames a refusal as "we couldn\'t read {Company}\'s board" and says why on the step', () => {
    renderWithProviders(<DiscoveryChecklist company={company('refused', REFUSED)} />);

    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(
      /we couldn't read acme's board/i,
    );
    // The reason rides the step that stopped, so "what went wrong" and "where" are one
    // thing to read rather than two.
    const failedStep = screen.getByTestId('discovery-step-verify_read');
    expect(within(failedStep).getByText('Building web scraper')).toBeInTheDocument();
    expect(within(failedStep).getByTestId('discovery-result-verify_read')).toHaveTextContent(
      /came back from the replay/i,
    );
  });

  it('offers one real alternative on a refusal — never a bare retry', () => {
    renderWithProviders(<DiscoveryChecklist company={company('refused', REFUSED)} />);

    const actions = screen.getByTestId('discovery-next-actions');
    // The fix for most refusals: the pasted URL was the marketing page, not the board.
    expect(within(actions).getByText(/click into a job/i)).toBeInTheDocument();
    expect(within(actions).getByText(/the page you pasted/i)).toHaveAttribute(
      'href',
      'https://careers.acme.example/jobs',
    );
    expect(within(actions).getByText(/tell us about this board/i)).toBeInTheDocument();
    // Cut: "Remove it." restated the Remove button a few pixels above.
    expect(within(actions).queryByText(/^remove it\.$/i)).not.toBeInTheDocument();
    // Discovery is deterministic — re-running the same URL reproduces the same refusal.
    expect(
      screen.queryByRole('button', { name: /try again|retry/i }),
    ).not.toBeInTheDocument();
  });

  it('reads a refused row as refused even when its blob still says "running"', () => {
    // The discovery TIMEOUT case: there was no outcome to write a terminal checklist
    // from, so the row flipped to `refused` while the last live snapshot survives. How
    // far we got is the useful part — but it must not read as "still working".
    const stalled = progress({
      steps: [
        step('open_page', 'done', 'opened careers.acme.example — recorded 3 JSON request(s)'),
        step('find_feed', 'active'),
        step('verify_read', 'pending'),
        step('ready', 'pending'),
      ],
    });
    renderWithProviders(<DiscoveryChecklist company={company('refused', stalled)} />);

    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute(
      'data-outcome',
      'refused',
    );
    expect(screen.getByTestId('discovery-stalled')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-next-actions')).toBeInTheDocument();
    // ...and NOTHING is still spinning. The stale `active` step is drawn as the rung we
    // never got past; an animated spinner on a terminated run makes the same row read as
    // finished and still working at once.
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('in progress')).not.toBeInTheDocument();
  });

  it('keeps the live spinner while the run really is still going', () => {
    // The other half of the pair above: the downgrade is keyed on the run being
    // terminal, so a `discovering` row must still animate its active step.
    renderWithProviders(<DiscoveryChecklist company={company('discovering', RUNNING)} />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders no iframe and no toggle when there is no live-view URL', async () => {
    // The DEFAULT: only a Browserbase capture has a hosted view and we run our own
    // Chromium, so this is the ordinary case, not the exception (DECISION D4).
    const { container } = renderWithProviders(
      <DiscoveryChecklist company={company('discovering', RUNNING)} />,
    );

    expect(screen.queryByTestId('discovery-live-view-toggle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-live-view')).not.toBeInTheDocument();
    expect(container.querySelectorAll('iframe')).toHaveLength(0);
    // ...and the checklist itself is intact — no gap where the video would go.
    expect(screen.getByTestId('discovery-step-open_page')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-step-ready')).toBeInTheDocument();
  });

  it('shows the live view straight away, read-only, when a session has one', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <DiscoveryChecklist
        company={company(
          'discovering',
          progress({
            ...RUNNING,
            liveViewUrl: 'https://www.browserbase.com/devtools-fullscreen/s/abc',
          }),
        )}
      />,
    );

    // EXPANDED on arrival. The session lasts about a minute; a run that ends before the
    // user notices a "Watch live" button showed them nothing at all.
    const frame = screen.getByTestId('discovery-live-view');
    // `navbar=false` strips the host's own chrome; the wrapper kills pointer events so
    // nobody can drive someone else's browser session from our page.
    expect(frame).toHaveAttribute('src', expect.stringContaining('navbar=false'));
    expect(getComputedStyle(frame.parentElement as HTMLElement).pointerEvents).toBe('none');

    // ...and it can still be put away.
    expect(screen.getByTestId('discovery-live-view-toggle')).toHaveTextContent(/hide live view/i);
    await user.click(screen.getByTestId('discovery-live-view-toggle'));
    expect(screen.getByTestId('discovery-live-view-toggle')).toHaveTextContent(/watch live/i);
  });

  it('renders no live-view box at all when there is no session to watch', () => {
    // The DEFAULT path: our own headless Chromium has no hosted view, so the checklist
    // must render exactly as it always has — no toggle, no empty frame, no layout shift.
    renderWithProviders(
      <DiscoveryChecklist company={company('discovering', progress({ ...RUNNING }))} />,
    );
    expect(screen.queryByTestId('discovery-live-view-toggle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-live-view')).not.toBeInTheDocument();
  });

  it('hides the live view once the run is over', () => {
    renderWithProviders(
      <DiscoveryChecklist
        company={company(
          'refused',
          progress({
            ...REFUSED,
            liveViewUrl: 'https://www.browserbase.com/devtools-fullscreen/s/abc',
          }),
        )}
      />,
    );
    // The session is gone by then — the URL would render a dead frame.
    expect(screen.queryByTestId('discovery-live-view-toggle')).not.toBeInTheDocument();
  });

  it('renders nothing at all for a company with no checklist', () => {
    const { container } = renderWithProviders(
      <DiscoveryChecklist company={company('unverified', null)} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
