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
 * - every landed step shows its SPECIFIC result ("found 3 candidate feeds", "read 90
 *   jobs"), never a bare tick — a generic checkmark is a spinner with extra steps;
 * - a refusal NAMES the step that stopped and offers real alternatives, never a bare
 *   "retry" (discovery is deterministic: the same URL reaches the same refusal, so a
 *   retry spends a browser session to reproduce an answer the user already has);
 * - success shows a job preview, so "we can read this board" is evidenced; and
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
    jobPreview: [],
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
  jobPreview: [
    { title: 'Staff Engineer', location: 'Remote', url: 'https://careers.acme.example/jobs/1' },
    { title: 'Product Designer', location: 'Berlin' },
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
  it('names all four steps, in order, whatever the state', () => {
    renderWithProviders(<DiscoveryChecklist company={company('discovering', RUNNING)} />);

    const list = screen.getByTestId('discovery-checklist');
    expect(within(list).getByText('Opening the careers page')).toBeInTheDocument();
    expect(within(list).getByText('Finding the jobs feed')).toBeInTheDocument();
    expect(within(list).getByText('Verifying we can read it')).toBeInTheDocument();
    expect(within(list).getByText('Ready to track')).toBeInTheDocument();
  });

  it('shows the SPECIFIC result of each landed step, not a generic tick', () => {
    renderWithProviders(<DiscoveryChecklist company={company('unverified', TRACKING)} />);

    expect(screen.getByTestId('discovery-result-open_page')).toHaveTextContent(
      /recorded 14 JSON request/i,
    );
    expect(screen.getByTestId('discovery-result-find_feed')).toHaveTextContent(
      'found 3 candidate feed(s)',
    );
    expect(screen.getByTestId('discovery-result-verify_read')).toHaveTextContent(
      'read 90 job(s)',
    );
  });

  it('renders a mid-run board as still working, with no result on the pending steps', () => {
    renderWithProviders(<DiscoveryChecklist company={company('discovering', RUNNING)} />);

    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute(
      'data-outcome',
      'running',
    );
    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(/setting up acme/i);
    expect(screen.queryByTestId('discovery-result-verify_read')).not.toBeInTheDocument();
    // Nothing to act on yet — the alternatives belong to a refusal.
    expect(screen.queryByTestId('discovery-next-actions')).not.toBeInTheDocument();
  });

  it('renders success as "we can read this board" plus a preview of real jobs', () => {
    renderWithProviders(<DiscoveryChecklist company={company('unverified', TRACKING)} />);

    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(
      /we can read acme's board/i,
    );
    const preview = screen.getByTestId('discovery-job-preview');
    expect(within(preview).getByText('Staff Engineer')).toHaveAttribute(
      'href',
      'https://careers.acme.example/jobs/1',
    );
    // A row the backend kept without a safe URL still renders — as plain text, not as
    // a dead link.
    expect(within(preview).getByText('Product Designer').tagName).not.toBe('A');
  });

  it('frames a refusal as "we couldn\'t read {Company}\'s board" and names the failed step', () => {
    renderWithProviders(<DiscoveryChecklist company={company('refused', REFUSED)} />);

    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(
      /we couldn't read acme's board/i,
    );
    // The ✓/✕ chain: "Found the jobs feed ✓ · Verifying we can read it ✕".
    const summary = screen.getByTestId('discovery-summary');
    expect(summary).toHaveTextContent('Finding the jobs feed ✓');
    expect(summary).toHaveTextContent('Verifying we can read it ✕');
    expect(screen.getByTestId('discovery-result-verify_read')).toHaveTextContent(
      /came back from the replay/i,
    );
  });

  it('offers real alternatives on a refusal — never a bare retry', () => {
    renderWithProviders(<DiscoveryChecklist company={company('refused', REFUSED)} />);

    const actions = screen.getByTestId('discovery-next-actions');
    expect(within(actions).getByText(/paste the direct board url/i)).toBeInTheDocument();
    expect(within(actions).getByText(/tell us about this board/i)).toBeInTheDocument();
    expect(within(actions).getByText(/^remove it\.$/i)).toBeInTheDocument();
    // The careers page is linked so the user can go find the embedded board.
    expect(within(actions).getByText(/this careers page/i)).toHaveAttribute(
      'href',
      'https://careers.acme.example/jobs',
    );
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

  it('offers the live view behind a toggle, read-only, when a session has one', async () => {
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

    // Collapsed by default: the checklist is the thing worth reading.
    expect(screen.getByTestId('discovery-live-view-toggle')).toHaveTextContent(/watch live/i);
    await user.click(screen.getByTestId('discovery-live-view-toggle'));

    const frame = screen.getByTestId('discovery-live-view');
    // `navbar=false` strips the host's own chrome; the wrapper kills pointer events so
    // nobody can drive someone else's browser session from our page.
    expect(frame).toHaveAttribute('src', expect.stringContaining('navbar=false'));
    expect(getComputedStyle(frame.parentElement as HTMLElement).pointerEvents).toBe('none');
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
