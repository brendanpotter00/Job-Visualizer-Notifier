import { describe, it, expect } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { DiscoveryNetworkLog } from '../../../components/my-companies/DiscoveryNetworkLog';
import type {
  DiscoveryNetwork,
  DiscoveryProgress,
  DiscoveryRequest,
  UserCompany,
} from '../../../features/userCompanies/userCompaniesApi';

/**
 * The network log — "show me what you're actually doing".
 *
 * The properties under test are the ones the whole panel exists for:
 *
 * - it is OPEN on arrival, because the rows landing three and four at a time ARE the
 *   streaming and a closed box has none of it in it;
 * - it NARROWS to the one request we picked as soon as there is one, with the JSON that
 *   request returned. That is what pays for opening it: many rows while we work, one row
 *   and a payload once we are done — and it happens the moment a winner exists, which is
 *   one publish before the run goes terminal;
 * - the discarded rows are one caption-sized link away, never deleted, and the heading
 *   keeps counting them ("14 requests · 1 picked");
 * - a REFUSAL has no winner, so nothing narrows and the whole list stays. That is the
 *   case the panel was built for: "none of these is a jobs list" with the list attached;
 *   and
 * - it renders NOTHING when nothing was recorded. A page that fetched no JSON at all
 *   has no evidence to show, and the checklist's ✕ already says exactly that.
 */

function request(overrides: Partial<DiscoveryRequest> = {}): DiscoveryRequest {
  return {
    method: 'GET',
    url: 'https://careers.acme.example/api/ping',
    status: 200,
    bytes: 512,
    records: 0,
    state: 'recorded',
    note: null,
    ...overrides,
  };
}

function network(overrides: Partial<DiscoveryNetwork> = {}): DiscoveryNetwork {
  return { requests: [request()], recorded: 1, sample: null, ...overrides };
}

function company(
  healthState: string,
  discoveryOverrides: Partial<DiscoveryProgress> = {},
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
    discovery: {
      steps: [],
      outcome: 'running',
      liveViewUrl: null,
      updatedAt: '2026-08-24T12:00:00Z',
      network: network(),
      ...discoveryOverrides,
    },
  };
}

/**
 * A settled, successful run: three rows survived the size budget out of fourteen we
 * saw, the last of them is the winner, and it carries the sample of what it returned.
 */
const PICKED: Partial<DiscoveryProgress> = {
  outcome: 'tracking',
  network: {
    recorded: 14,
    requests: [
      request({ url: 'https://careers.acme.example/api/session' }),
      request({ url: 'https://careers.acme.example/graphql/flags' }),
      request({
        url: 'https://careers.acme.example/api/jobs?limit=…',
        state: 'chosen',
        records: 88,
        note: '88 job(s) came back when we replayed it from our own servers',
      }),
    ],
    sample: { path: 'data.jobs', records: 88, text: '{\n  "title": "Staff Engineer"\n}' },
  },
};

/**
 * The SAME capture one poll earlier: the three rows are there, none of them has won yet.
 * Rerendering from this into `PICKED` is the only way to exercise the narrowing as an
 * EVENT rather than as an initial state, which is the difference the collapse turns on.
 */
const SEARCHING: Partial<DiscoveryProgress> = {
  outcome: 'running',
  network: {
    recorded: 14,
    requests: [
      request({ url: 'https://careers.acme.example/api/session' }),
      request({ url: 'https://careers.acme.example/graphql/flags' }),
      request({ url: 'https://careers.acme.example/api/jobs?limit=…', records: null }),
    ],
    sample: null,
  },
};

describe('DiscoveryNetworkLog', () => {
  it('is OPEN on arrival, with the rows already showing', async () => {
    // The rows landing while the browser is open are the only watchable part of a
    // one-time setup. Collapsed by default, that happened inside a closed box.
    renderWithProviders(<DiscoveryNetworkLog company={company('discovering')} />);

    expect(screen.getByTestId('discovery-network-toggle')).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getByTestId('discovery-request-list')).toBeInTheDocument();

    // ...and it can still be put away, to NOTHING — not a 0px box full of list items.
    // `waitFor` because `unmountOnExit` drops the subtree when the exit SETTLES, not
    // when the click lands.
    await userEvent.click(screen.getByTestId('discovery-network-toggle'));
    expect(screen.getByTestId('discovery-network-toggle')).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    await waitFor(() => {
      expect(screen.queryByTestId('discovery-request-list')).not.toBeInTheDocument();
    });
  });

  it('counts the requests as they stream in, while the run is still going', () => {
    // The count IS the streaming, visible without opening anything. A generic
    // "Show details" here would have been a spinner with a chevron on it.
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('discovering', {
          network: network({
            requests: [request(), request(), request()],
            recorded: 3,
          }),
        })}
      />
    );
    expect(screen.getByText('3 requests so far')).toBeInTheDocument();
  });

  it('keeps the WHOLE list on a refusal — there is no winner to narrow to', () => {
    // THE case this was built for, and the one case narrowing must never touch.
    // "None of the requests this page made is a list of job postings" is a conclusion;
    // every one of these rows is the evidence for it, so all of them stay on screen
    // with no link standing between the reader and them.
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('refused', {
          outcome: 'refused',
          network: network({
            requests: [
              request({ url: 'https://careers.acme.example/api/session', records: 0 }),
              request({ url: 'https://careers.acme.example/graphql/flags', records: 0 }),
              request({ url: 'https://careers.acme.example/api/tracking', records: 0 }),
            ],
            recorded: 3,
          }),
        })}
      />
    );
    expect(screen.getByText('3 requests · none we could use')).toBeInTheDocument();
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(3);
    expect(screen.getByTestId('discovery-request-list')).toHaveAttribute(
      'data-narrowed',
      'false'
    );
    expect(screen.queryByTestId('discovery-show-all')).not.toBeInTheDocument();
  });

  it('narrows to the ONE it picked, with the JSON that request sent back', async () => {
    // THE literal ask: once a request has been chosen, show that one — not fourteen
    // rows with one of them highlighted.
    renderWithProviders(<DiscoveryNetworkLog company={company('unverified', PICKED)} />);

    const rows = screen.getAllByTestId('discovery-request');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute('data-state', 'chosen');
    expect(within(rows[0]).getByText('Picked')).toBeInTheDocument();
    expect(
      within(rows[0]).getByText(/88 job\(s\) came back when we replayed it/)
    ).toBeInTheDocument();
    expect(screen.getByTestId('discovery-request-list')).toHaveAttribute(
      'data-narrowed',
      'true'
    );

    // ...and the payload sits directly under the one row it came from.
    const sample = screen.getByTestId('discovery-payload-sample');
    expect(within(sample).getByText(/One of the 88 records it sent back/)).toBeInTheDocument();
    expect(within(sample).getByText(/Staff Engineer/)).toBeInTheDocument();
  });

  it('keeps the discarded rows one link away, and the heading keeps counting them', async () => {
    // Narrowing must not DELETE the evidence: "why did you pick that one and not the
    // endpoint I can see in my own devtools" is a real question on a partial board.
    renderWithProviders(<DiscoveryNetworkLog company={company('unverified', PICKED)} />);

    // `recorded`, not the row count: the stored list is clipped to a size budget, and
    // this line is now the ONLY thing saying there were fourteen at all.
    expect(screen.getByText('14 requests · 1 picked')).toBeInTheDocument();

    await userEvent.click(screen.getByTestId('discovery-show-all'));
    const shown = screen.getAllByTestId('discovery-request');
    expect(shown).toHaveLength(3);
    expect(shown.map((row) => row.getAttribute('data-state'))).toEqual([
      'recorded',
      'recorded',
      'chosen',
    ]);

    // ...and back to the calm state. SYNCHRONOUSLY: a deliberate click is never
    // animated, only the automatic narrowing is. See the collapse test below.
    await userEvent.click(screen.getByTestId('discovery-show-all'));
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(1);
  });

  it('lets the displaced rows collapse away instead of vanishing between two frames', async () => {
    // The narrowing is the most legible thing this panel does — fourteen rows become one
    // — and it used to happen between two frames, which reads as the layout glitching
    // rather than as an answer being found. So the rows a winner displaces stay mounted
    // for exactly one collapse and are dropped when it has played.
    const { rerender } = renderWithProviders(
      <DiscoveryNetworkLog company={company('discovering', SEARCHING)} />
    );
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(3);

    // The winner lands on the next poll — nobody clicked anything.
    rerender(<DiscoveryNetworkLog company={company('discovering', PICKED)} />);

    // STILL THREE. This is the whole assertion: the two it displaced are on their way
    // out, not already gone, so there is something left to animate.
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(3);

    // ...and then they go, on their own.
    await waitFor(() =>
      expect(screen.getAllByTestId('discovery-request')).toHaveLength(1)
    );
  });

  it('does NOT replay the collapse on a row that was already settled when it mounted', () => {
    // A settled board is the common case — every reload of a tracked row mounts with its
    // winner already chosen. There is no search to watch end there, so animating one
    // would be a lie about when it happened AND would fire on every single render of the
    // list. One row, first frame, no window.
    renderWithProviders(<DiscoveryNetworkLog company={company('unverified', PICKED)} />);
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(1);
  });

  it('narrows the moment a winner EXISTS, not a poll later', () => {
    // `choose_request` is written during `verify_read`, one publish before the terminal
    // write flips `health_state` — so running-with-a-winner is a real combination, and
    // keying the narrowing on the outcome would leave a settled answer looking like an
    // open search. The heading has to agree with the list it heads, too.
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('discovering', {
          outcome: 'running',
          network: network({
            requests: [request(), request({ state: 'chosen', records: 88 })],
            recorded: 2,
          }),
        })}
      />
    );
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(1);
    expect(screen.getByText('2 requests · 1 picked')).toBeInTheDocument();
  });

  it('offers no "show the others" when the winner is the only thing we recorded', () => {
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('unverified', {
          outcome: 'tracking',
          network: network({
            requests: [request({ state: 'chosen', records: 88 })],
            recorded: 1,
          }),
        })}
      />
    );
    expect(screen.getAllByTestId('discovery-request')).toHaveLength(1);
    expect(screen.queryByTestId('discovery-show-all')).not.toBeInTheDocument();
  });

  it('tells "we have not looked yet" apart from "we looked and found nothing"', () => {
    // `records: null` lands on every row while the browser is still open; `0` is the
    // pre-filter's verdict. Collapsing them would make a mid-run capture claim we had
    // already ruled every request out.
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('discovering', {
          network: network({
            requests: [
              request({ records: null, bytes: 2048 }),
              request({ records: 0, bytes: 1536 }),
              request({ records: 12, bytes: 1024 * 90 }),
            ],
            recorded: 3,
          }),
        })}
      />
    );

    const details = screen.getAllByTestId('discovery-request-detail').map((n) => n.textContent);
    expect(details).toEqual(['2.0 KB', '1.5 KB — no job postings in it', '90.0 KB — 12 job postings']);
  });

  it('blames our own ceiling for an oversize body, not the board', () => {
    // Measured on binance.com: a 2.78 MB jobs feed was dropped by our cap and the
    // refusal told the user their board had no jobs feed. The row has to say whose
    // limit it was.
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('refused', {
          outcome: 'refused',
          network: network({
            requests: [request({ state: 'oversize', records: null, bytes: 2_775_685 })],
            recorded: 1,
          }),
        })}
      />
    );
    expect(
      screen.getByText('2.6 MB — bigger than we can read in one go')
    ).toBeInTheDocument();
  });

  it('renders nothing at all when the page fetched no JSON', () => {
    // metacareers.com, measured: zero XHRs recorded. There is no evidence to show, the
    // checklist's ✕ already says so, and a second component restating it is exactly the
    // say-it-four-times problem this panel was cut back from.
    const { container } = renderWithProviders(
      <DiscoveryNetworkLog
        company={company('refused', {
          outcome: 'refused',
          network: { requests: [], recorded: 0, sample: null },
        })}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a server that predates the network log', () => {
    const stale = company('discovering');
    delete stale.discovery!.network;
    const { container } = renderWithProviders(<DiscoveryNetworkLog company={stale} />);
    expect(container).toBeEmptyDOMElement();
  });
});
