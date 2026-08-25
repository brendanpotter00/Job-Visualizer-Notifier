import { describe, it, expect, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
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
 *   there is no iframe, no toggle, and nothing missing from the layout; and
 * - the live view is torn down when the BROWSER closes, not when the RUN ends. Those are
 *   ~60 seconds apart and the frame used to sit there the whole time rendering
 *   Browserbase's own "WebSocket disconnected" across a 16:10 box, on every SUCCESSFUL
 *   run. The trigger is the backend nulling `liveViewUrl` at release — NOT anything
 *   derived from the checklist. An earlier fix keyed it on `open_page` leaving `active`
 *   and a screenshot disproved that: the step was still bold and spinning while the
 *   frame under it already showed the dead socket; and
 * - the network log renders BELOW the live view. While a browser is open the frame is
 *   the headline and the requests are its record, so rows arriving must not push the
 *   only watchable thing on the page down.
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

/**
 * Mid-run, and PAST the capture: `open_page` has ticked over and the run is still
 * `running` for another ~60s. It carries no `liveViewUrl`, which is the ONLY reason
 * there is nothing to watch — the ticked step says nothing about it either way.
 */
const RUNNING = progress({
  steps: [
    step('open_page', 'done', 'opened careers.acme.example — recorded 14 JSON request(s)'),
    step('find_feed', 'active'),
    step('verify_read', 'pending'),
    step('ready', 'pending'),
  ],
});

const LIVE_VIEW_URL = 'https://www.browserbase.com/devtools-fullscreen/s/abc';

/**
 * The window in which a hosted session is watchable: the backend has published a URL and
 * has not yet nulled it. ~30 seconds of a ~90 second run. `open_page` is `active` here
 * only because that is what a real mid-capture blob looks like — nothing reads it.
 */
const CAPTURING = progress({
  liveViewUrl: LIVE_VIEW_URL,
  steps: [
    step('open_page', 'active'),
    step('find_feed', 'pending'),
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

  it('shows the live view straight away, read-only, while the browser is open', async () => {
    const user = userEvent.setup();
    renderWithProviders(<DiscoveryChecklist company={company('discovering', CAPTURING)} />);

    // EXPANDED on arrival. The session lasts about thirty seconds; a run that ends
    // before the user notices a "Watch live" button showed them nothing at all.
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

  it('reserves ZERO height when there is no live view — not an empty box', () => {
    // The strongest form of "no dead space": with no URL the section is not in the DOM
    // at all, so there is no node that could have a height. A `Collapse` left mounted at
    // `height: 0` would satisfy the eye and still be a node; `unmountOnExit` is what
    // makes this assertion possible.
    const { container } = renderWithProviders(
      <DiscoveryChecklist company={company('discovering', progress({ ...RUNNING }))} />,
    );
    expect(screen.queryByTestId('discovery-live-view-section')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-live-view-frame')).not.toBeInTheDocument();
    expect(container.querySelectorAll('iframe')).toHaveLength(0);
    // The checklist itself is whole — the panel's last child is the fourth rung, with
    // nothing after it.
    expect(screen.getByTestId('discovery-step-ready')).toBeInTheDocument();
  });

  it('unmounts the frame the instant the URL goes null — even mid-step', () => {
    // THE BUG, AND THE SHAPE THE PREVIOUS FIX GOT WRONG.
    //
    // That fix tore the frame down when `open_page` stopped being `active`, on the
    // theory that the backend releases the session and ticks the step in one breath. A
    // screenshot disproved it: `Opening the page` was still bold with its spinner
    // turning while the frame beneath it already read "Debugging connection was closed.
    // Reason: WebSocket disconnected" over a white box. The CDP socket dies when the
    // BROWSER closes, which is strictly before the ledger write that moves the step, and
    // that gap is where the dead frame lives.
    //
    // So this pins the case the screenshot showed: `open_page` STILL ACTIVE, run still
    // `running`, and only `liveViewUrl` going null — which is what the backend now
    // publishes at release. Nothing about the checklist may be consulted.
    const { container, rerender } = renderWithProviders(
      <DiscoveryChecklist company={company('discovering', CAPTURING)} />,
    );
    expect(screen.getByTestId('discovery-live-view')).toBeInTheDocument();

    const released = progress({ ...CAPTURING, liveViewUrl: null });
    rerender(<DiscoveryChecklist company={company('discovering', released)} />);

    // Everything the old rule looked at is UNCHANGED: still running, step 1 still
    // active, still spinning. Only the URL moved.
    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute('data-outcome', 'running');
    expect(released.steps[0]).toMatchObject({ key: 'open_page', status: 'active' });
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    // GONE, not hidden: while it is mounted it is Browserbase's page and it is free to
    // paint their error text into our layout. No styling answers that.
    expect(screen.queryByTestId('discovery-live-view')).not.toBeInTheDocument();
    expect(container.querySelectorAll('iframe')).toHaveLength(0);
  });

  it('keeps watching while the URL stands, even after step 1 has ticked over', () => {
    // The other half of the correction, and the reason it is not just a stricter
    // version of the old rule: a session the backend has NOT released must keep
    // rendering, whatever the checklist says. Inferring death from step state killed
    // live views that were still alive as readily as it missed dead ones.
    renderWithProviders(
      <DiscoveryChecklist
        company={company('discovering', progress({ ...RUNNING, liveViewUrl: LIVE_VIEW_URL }))}
      />,
    );
    expect(screen.getByTestId('discovery-live-view')).toBeInTheDocument();
  });

  it('closes the space smoothly and ends with nothing in it', async () => {
    const { rerender } = renderWithProviders(
      <DiscoveryChecklist company={company('discovering', CAPTURING)} />,
    );
    const frameBox = screen.getByTestId('discovery-live-view-frame');
    const panel = screen.getByTestId('discovery-checklist');

    rerender(
      <DiscoveryChecklist
        company={company('discovering', progress({ ...CAPTURING, liveViewUrl: null }))}
      />,
    );

    // NO JUMP. The sized wrapper is the SAME node, still mounted and still holding the
    // shape — that is what `Collapse` measures to know the height to animate down from.
    // Tearing it out with the iframe would drop ~375px in one frame and then animate the
    // 36px remainder: a jump followed by a slide.
    expect(screen.getByTestId('discovery-live-view-frame')).toBe(frameBox);
    // ...and the checklist above it never remounts, so the rungs the user is reading
    // stay exactly where they are.
    expect(screen.getByTestId('discovery-checklist')).toBe(panel);

    // AND IT ENDS AT NOTHING. Once the exit settles the whole section is unmounted —
    // no toggle for a session that is over, no 0px box, nothing.
    await waitFor(() => {
      expect(screen.queryByTestId('discovery-live-view-section')).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('discovery-live-view-frame')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-live-view-toggle')).not.toBeInTheDocument();
  });

  it('takes the space back from a frame that never loads', () => {
    // A frame that shows nothing is the same dead space as a frame showing a dead
    // socket. NOTE the signal: `onError` on an <iframe> can never fire — react-dom 19
    // attaches only `load` for the iframe tag — so the watchdog is keyed on the ABSENCE
    // of a `load` rather than on a failure event that does not exist.
    vi.useFakeTimers();
    try {
      renderWithProviders(<DiscoveryChecklist company={company('discovering', CAPTURING)} />);
      expect(screen.getByTestId('discovery-live-view')).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(10_000);
      });

      expect(screen.queryByTestId('discovery-live-view')).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('leaves a frame that DID load alone', () => {
    // The other half of the watchdog, and the one that matters: it must not delete a
    // working live view. A frame that reports `load` is never touched again, however
    // long the capture then takes.
    vi.useFakeTimers();
    try {
      renderWithProviders(<DiscoveryChecklist company={company('discovering', CAPTURING)} />);
      fireEvent.load(screen.getByTestId('discovery-live-view'));

      act(() => {
        vi.advanceTimersByTime(60_000);
      });

      expect(screen.getByTestId('discovery-live-view')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('hides the live view once the run is over', () => {
    renderWithProviders(
      <DiscoveryChecklist
        company={company('refused', progress({ ...REFUSED, liveViewUrl: LIVE_VIEW_URL }))}
      />,
    );
    // The session is gone by then — the URL would render a dead frame.
    expect(screen.queryByTestId('discovery-live-view-toggle')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-live-view')).not.toBeInTheDocument();
  });

  it('shows nothing to watch on a run that TIMED OUT mid-capture', () => {
    // The stalled-snapshot case: the 240s guard cancels the task while `open_page` is
    // still `active`, so the blob freezes with a live-looking step AND a URL. The row
    // flips to `refused`. The browser is long gone — "step 1 is active" is only a live
    // browser while the run itself is still live.
    const stalledMidCapture = progress({
      liveViewUrl: LIVE_VIEW_URL,
      steps: [
        step('open_page', 'active'),
        step('find_feed', 'pending'),
        step('verify_read', 'pending'),
        step('ready', 'pending'),
      ],
    });
    renderWithProviders(<DiscoveryChecklist company={company('refused', stalledMidCapture)} />);

    expect(screen.queryByTestId('discovery-live-view')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-live-view-section')).not.toBeInTheDocument();
  });

  it('puts the network log BELOW the live view', () => {
    // The live view is the headline while a browser is open — it is the one thing on the
    // page a person can literally watch — and the requests are the record that browser
    // is producing. With the log above, every batch of arriving rows shoved the frame
    // further down the page under the reader's eye.
    renderWithProviders(
      <DiscoveryChecklist
        company={company('discovering', {
          ...CAPTURING,
          network: {
            recorded: 2,
            requests: [
              { method: 'GET', url: 'https://acme.example/a', status: 200, bytes: 512, records: null, state: 'recorded', note: null },
              { method: 'GET', url: 'https://acme.example/b', status: 200, bytes: 512, records: null, state: 'recorded', note: null },
            ],
            sample: null,
          },
        })}
      />,
    );

    const liveView = screen.getByTestId('discovery-live-view-section');
    const log = screen.getByTestId('discovery-network');
    // DOCUMENT_POSITION_FOLLOWING: the log comes after the live view in document order.
    expect(liveView.compareDocumentPosition(log) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // ...and both are really on screen — an ordering assertion over a missing node
    // passes for the wrong reason.
    expect(screen.getByTestId('discovery-live-view')).toBeInTheDocument();
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(2);
  });

  it('renders nothing at all for a company with no checklist', () => {
    const { container } = renderWithProviders(
      <DiscoveryChecklist company={company('unverified', null)} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});


describe('the first-scan rung', () => {
  // `first_scan` is settled by the FIRST HARVEST — a different run that begins AFTER
  // discovery has already reached its terminal outcome ('tracking'). It is therefore the
  // one rung legitimately `active` while the outcome is not `running`, and the spinner on
  // it is the only signal that anything is still happening. Before it existed the panel
  // went fully green while the row still read "0 open jobs": every rung was true, and the
  // thing the user was actually waiting for had no rung at all.
  const scanning = (status: DiscoveryStep['status'], result?: string) =>
    progress({
      outcome: 'tracking',
      steps: [
        step('open_page', 'done', 'opened careers.acme.example — recorded 14 JSON request(s)'),
        step('find_feed', 'done', 'found 3 candidate feed(s)'),
        step('verify_read', 'done', 'read 88 job(s)'),
        step('ready', 'done', "reading the board's own feed directly — no browser needed"),
        step('first_scan', status, result),
      ],
    });

  it('names the fifth rung in words, never its raw key', () => {
    renderWithProviders(<DiscoveryChecklist company={company('unverified', scanning('active'))} />);
    // "Fetching all current jobs", not "Reading the board". This rung IS the first
    // harvest, and the word "all" is what a partial board cannot honestly tick.
    expect(screen.getByText('Fetching all current jobs')).toBeInTheDocument();
    expect(screen.queryByText('first_scan')).not.toBeInTheDocument();
  });

  it('keeps its spinner while the harvest runs, even though the outcome is terminal', () => {
    renderWithProviders(<DiscoveryChecklist company={company('unverified', scanning('active'))} />);
    const row = screen.getByTestId('discovery-step-first_scan');
    // Every OTHER rung is downgraded active -> pending once the outcome settles. This one
    // must not be, or the only thing still happening draws as a grey circle.
    expect(within(row).getByLabelText('in progress')).toBeInTheDocument();
  });

  it('settles to a plain tick, without the engine telemetry, once the harvest lands', () => {
    renderWithProviders(
      <DiscoveryChecklist
        company={company('unverified', scanning('done', 'read 88 job(s) from the board'))}
      />,
    );
    const row = screen.getByTestId('discovery-step-first_scan');
    expect(within(row).getByText('Fetching all current jobs')).toBeInTheDocument();
    // No spinner — this rung is finished.
    expect(within(row).queryByLabelText('in progress')).not.toBeInTheDocument();
    // Per-step detail rides ONLY on a failed rung. On a done one it is engine telemetry,
    // and the real job count belongs on the row itself once the harvest sets lastSuccessAt.
    expect(screen.queryByText(/read 88 job\(s\) from the board/)).not.toBeInTheDocument();
  });

  it('a failed first scan carries its reason and does NOT read as a refusal', () => {
    renderWithProviders(
      <DiscoveryChecklist
        company={company(
          'unverified',
          scanning('failed', 'we could not read the board on this run — we will try again'),
        )}
      />,
    );
    expect(screen.getByText(/we will try again/)).toBeInTheDocument();
    // The board IS tracked — a bad first harvest must never present as "not trackable".
    expect(screen.queryByText(/couldn.t read/i)).not.toBeInTheDocument();
  });

  it('draws a failed first scan CALMLY — no ✕, no red, because there is nothing to do', () => {
    // THE SAME ANTI-PATTERN AS THE AMBER CHIP, pointing the other way. This rung used to
    // draw the exact red ✕ a refusal draws, under a chip that said the board was being
    // tracked — and the scheduler retries tonight on its own, so there is no button, no
    // URL to change, nothing the reader can do. Alarm chrome over a no-op teaches people
    // to ignore alarm chrome.
    renderWithProviders(
      <DiscoveryChecklist
        company={company(
          'unverified',
          scanning('failed', 'we could not read the board on this run — we will try again'),
        )}
      />,
    );
    const row = screen.getByTestId('discovery-step-first_scan');
    expect(within(row).queryByText('✕')).not.toBeInTheDocument();
    expect(within(row).getByText('○')).toBeInTheDocument();
    // The reason still shows — only the colour changed.
    expect(within(row).getByTestId('discovery-result-first_scan')).toHaveTextContent(
      /we will try again/,
    );
  });

  it('leaves the ✕ exactly where it belongs — on a refusal', () => {
    // The other half: calming the unactionable states must not calm the one state the
    // reader CAN act on. A refused board keeps its red ✕, and it is the only thing that
    // says whether the pasted URL was the wrong page.
    renderWithProviders(<DiscoveryChecklist company={company('refused', REFUSED)} />);
    expect(
      within(screen.getByTestId('discovery-step-verify_read')).getByText('✕'),
    ).toBeInTheDocument();
  });

  it('spends the alarm colour on the refusal and on nothing else', () => {
    // The rule, asserted as a comparison rather than against a hard-coded rgb: the one
    // detail line a reader can act on is a different colour from the one they cannot.
    // Without this, quietening the retry line and quietening the REFUSAL line look the
    // same to the suite — which is how a fix for over-alarming turns into under-alarming.
    const { unmount } = renderWithProviders(
      <DiscoveryChecklist company={company('refused', REFUSED)} />,
    );
    const refusal = getComputedStyle(
      screen.getByTestId('discovery-result-verify_read'),
    ).color;
    unmount();

    renderWithProviders(
      <DiscoveryChecklist
        company={company(
          'unverified',
          scanning('failed', 'we could not read the board on this run — we will try again'),
        )}
      />,
    );
    const retry = getComputedStyle(screen.getByTestId('discovery-result-first_scan')).color;

    expect(refusal).not.toBe('');
    expect(retry).not.toBe('');
    expect(retry).not.toBe(refusal);
  });
});

describe('a partial board, and the rung that used to argue with its chip', () => {
  // THE CONTRADICTION. Five unqualified ✓s — the last of them reading as complete
  // success — under a chip saying we only read part of the board. The chip was the
  // correct one, so the fix is the last rung saying what it actually achieved. Then the
  // chip corroborates the list instead of looking like a malfunction.
  const PARTIAL = progress({
    outcome: 'partial',
    steps: [
      step('open_page', 'done', 'opened careers.acme.example — recorded 16 JSON request(s)'),
      step('find_feed', 'done', 'found 3 candidate feed(s)'),
      step(
        'verify_read',
        'done',
        "read 20 job(s), but this board's own response counts 22,500 job(s) — we can only " +
          'track part of this board',
      ),
      step('ready', 'done', 'reading part of the board — every job we can see, refreshed daily'),
      step('first_scan', 'done', 'read 1,000 job(s) from the board'),
    ],
  });

  const partialCompany = () =>
    company('unverified', PARTIAL, { openJobCount: 1_000, lastSuccessAt: null });

  it('marks the LAST rung ◐ and puts the board’s own numbers under it', () => {
    renderWithProviders(<DiscoveryChecklist company={partialCompany()} />);

    const row = screen.getByTestId('discovery-step-first_scan');
    expect(within(row).getByText('◐')).toBeInTheDocument();
    expect(within(row).queryByText('✓')).not.toBeInTheDocument();
    expect(within(row).getByTestId('discovery-result-first_scan')).toHaveTextContent(
      "This board's own response counts 22,500 job(s); we can reach 1,000.",
    );
  });

  it('leaves the four CAPABILITY rungs as plain ticks', () => {
    // Every one of them fully succeeded: we opened the page, read jobs, built a scraper,
    // and are ready to track. Only COVERAGE is partial. Qualifying all five would mark
    // four true things to fix one false one — and cost the list the scannability it was
    // cut back to get.
    renderWithProviders(<DiscoveryChecklist company={partialCompany()} />);

    for (const key of ['open_page', 'find_feed', 'verify_read', 'ready']) {
      const row = screen.getByTestId(`discovery-step-${key}`);
      expect(within(row).getByText('✓')).toBeInTheDocument();
      expect(within(row).queryByText('◐')).not.toBeInTheDocument();
    }
    // ...and none of them leaked engine telemetry to get there.
    expect(screen.queryByText(/JSON request/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/candidate feed/i)).not.toBeInTheDocument();
  });

  it('never shows the ACCEPTANCE PROBE’s count, which contradicts the row', () => {
    // The backend's sentence opens with "read 20 job(s)" — the two-page acceptance
    // probe — on a row whose chip says 1,000 open jobs. Printing it verbatim would
    // answer one confusion with a worse one.
    renderWithProviders(<DiscoveryChecklist company={partialCompany()} />);
    expect(screen.queryByText(/read 20 job/)).not.toBeInTheDocument();
    // ...and the verdict clause is not repeated under a heading that already says it.
    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(
      /we can only read part of acme's board/i,
    );
    expect(screen.queryByText(/we can only track part of this board/)).not.toBeInTheDocument();
  });

  it('keeps its ✓ while the harvest is still running — partial is not known yet', () => {
    // A partial verdict is decided at DISCOVERY time; the harvest runs afterwards. A ◐
    // over a count that is still climbing asserts the end of a story mid-sentence.
    const stillFetching = progress({
      ...PARTIAL,
      steps: [...PARTIAL.steps.slice(0, 4), step('first_scan', 'active')],
    });
    renderWithProviders(
      <DiscoveryChecklist company={company('unverified', stillFetching, { openJobCount: 0 })} />,
    );
    const row = screen.getByTestId('discovery-step-first_scan');
    expect(within(row).getByLabelText('in progress')).toBeInTheDocument();
    expect(within(row).queryByText('◐')).not.toBeInTheDocument();
    // ...and the heading narrates rather than concluding.
    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(/fetching acme's jobs/i);
  });

  it('marks nothing on a board we read WHOLE', () => {
    const whole = progress({
      ...PARTIAL,
      outcome: 'tracking',
      steps: [...PARTIAL.steps.slice(0, 4), step('first_scan', 'done', 'read 90 job(s)')],
    });
    renderWithProviders(<DiscoveryChecklist company={company('unverified', whole)} />);
    const row = screen.getByTestId('discovery-step-first_scan');
    expect(within(row).getByText('✓')).toBeInTheDocument();
    expect(within(row).queryByText('◐')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-result-first_scan')).not.toBeInTheDocument();
  });
});

describe('the accordion', () => {
  const settled = (overrides: Partial<UserCompany> = {}) =>
    company('unverified', progress({ outcome: 'tracking', steps: TRACKING.steps }), {
      openJobCount: 42,
      lastSuccessAt: '2026-08-22T00:00:00Z',
      ...overrides,
    });

  it('is CLOSED on a settled row — one line, and nothing else in the DOM', () => {
    const { container } = renderWithProviders(<DiscoveryChecklist company={settled()} />);

    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute('data-open', 'false');
    expect(screen.getByTestId('discovery-headline')).toHaveTextContent(
      /we can read acme's board/i,
    );
    // `unmountOnExit`: the rungs are absent, not hidden. That is what makes it
    // affordable to keep the evidence on every tracked row forever.
    expect(screen.queryByTestId('discovery-step-open_page')).not.toBeInTheDocument();
    expect(container.querySelectorAll('iframe')).toHaveLength(0);
    expect(screen.getByTestId('discovery-toggle')).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens on a click, and closes again', async () => {
    const user = userEvent.setup();
    renderWithProviders(<DiscoveryChecklist company={settled()} />);

    await user.click(screen.getByTestId('discovery-toggle'));
    expect(screen.getByTestId('discovery-step-open_page')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-toggle')).toHaveAttribute('aria-expanded', 'true');

    await user.click(screen.getByTestId('discovery-toggle'));
    expect(screen.getByTestId('discovery-toggle')).toHaveAttribute('aria-expanded', 'false');
  });

  it('is OPEN while the setup is running — the streaming must not happen in a box', () => {
    renderWithProviders(<DiscoveryChecklist company={company('discovering', RUNNING)} />);
    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute('data-open', 'true');
    expect(screen.getByTestId('discovery-step-open_page')).toBeInTheDocument();
  });

  it('is OPEN on a refusal — the verdict and its one action need no click', () => {
    renderWithProviders(<DiscoveryChecklist company={company('refused', REFUSED)} />);
    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute('data-open', 'true');
    expect(screen.getByTestId('discovery-next-actions')).toBeInTheDocument();
  });

  it('is OPEN on an accepted board whose first harvest has not landed', () => {
    // `first_scan` is still spinning; that is the only thing happening and it is the
    // thing the user is waiting on.
    renderWithProviders(<DiscoveryChecklist company={company('unverified', TRACKING)} />);
    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute('data-open', 'true');
  });

  it('does NOT slam shut when the harvest lands under a reader', () => {
    // The open state is read ONCE, on mount. A panel that closed itself mid-sentence —
    // at the exact moment the rung being read ticked over — would be the worst possible
    // time to take it away.
    const { rerender } = renderWithProviders(
      <DiscoveryChecklist company={company('unverified', TRACKING)} />,
    );
    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute('data-open', 'true');

    rerender(<DiscoveryChecklist company={settled()} />);
    expect(screen.getByTestId('discovery-checklist')).toHaveAttribute('data-open', 'true');
    expect(screen.getByTestId('discovery-step-open_page')).toBeInTheDocument();
  });
});
