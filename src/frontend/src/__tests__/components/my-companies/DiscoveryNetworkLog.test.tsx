import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
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
 * - it is COLLAPSED in every state, because the checklist above it was cut back for
 *   being busy and a forty-row log would undo that on the first chatty board. What it
 *   adds by default is one summary line;
 * - that line is never generic. It carries a live count while the browser is open
 *   (which is what "streaming" looks like in one line) and the verdict afterwards;
 * - the request we PICKED is visibly not one of the also-rans, and the JSON it returned
 *   is one click away — that is the literal ask;
 * - it is as useful on a REFUSAL as on a success, which is the case it was built for:
 *   "none of these is a jobs list" with the list attached; and
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

describe('DiscoveryNetworkLog', () => {
  it('adds ONE line by default and hides the rows behind it', async () => {
    // The declutter constraint, stated as a test: the panel above this was cut from
    // ~14 lines to ~8, and this must not put them back.
    renderWithProviders(<DiscoveryNetworkLog company={company('discovering')} />);

    expect(screen.getByTestId('discovery-network-toggle')).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    expect(screen.queryByTestId('discovery-request-list')).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId('discovery-network-toggle'));
    expect(screen.getByTestId('discovery-request-list')).toBeInTheDocument();
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

  it('says which one it picked once the run has settled', () => {
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('unverified', {
          outcome: 'tracking',
          network: network({
            requests: [request(), request({ state: 'chosen', records: 88 })],
            recorded: 14,
          }),
        })}
      />
    );
    // `recorded`, not the row count: the stored list is clipped to a size budget and
    // the headline stays truthful about what we SAW.
    expect(screen.getByText('14 requests · 1 picked')).toBeInTheDocument();
  });

  it('is as useful on a refusal as on a success', () => {
    // THE case this was built for. "None of the 14 JSON requests this page made is a
    // list of job postings" is a conclusion; these rows are the evidence for it.
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('refused', {
          outcome: 'refused',
          network: network({
            requests: [
              request({ url: 'https://careers.acme.example/api/session', records: 0 }),
              request({ url: 'https://careers.acme.example/graphql/flags', records: 0 }),
            ],
            recorded: 2,
          }),
        })}
      />
    );
    expect(screen.getByText('2 requests · none we could use')).toBeInTheDocument();
  });

  it('marks the chosen request and shows the JSON it sent back', async () => {
    renderWithProviders(
      <DiscoveryNetworkLog
        company={company('unverified', {
          outcome: 'tracking',
          network: {
            recorded: 2,
            requests: [
              request({ url: 'https://careers.acme.example/api/ping' }),
              request({
                url: 'https://careers.acme.example/api/jobs?limit=…',
                state: 'chosen',
                records: 88,
                note: '88 job(s) came back when we replayed it from our own servers',
              }),
            ],
            sample: {
              path: 'data.jobs',
              records: 88,
              text: '{\n  "title": "Staff Engineer"\n}',
            },
          },
        })}
      />
    );
    await userEvent.click(screen.getByTestId('discovery-network-toggle'));

    const rows = screen.getAllByTestId('discovery-request');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute('data-state', 'recorded');
    expect(rows[1]).toHaveAttribute('data-state', 'chosen');
    expect(within(rows[1]).getByText('Picked')).toBeInTheDocument();
    expect(
      within(rows[1]).getByText(/88 job\(s\) came back when we replayed it/)
    ).toBeInTheDocument();

    const sample = screen.getByTestId('discovery-payload-sample');
    expect(within(sample).getByText(/One of the 88 records it sent back/)).toBeInTheDocument();
    expect(within(sample).getByText(/Staff Engineer/)).toBeInTheDocument();
  });

  it('tells "we have not looked yet" apart from "we looked and found nothing"', async () => {
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
    await userEvent.click(screen.getByTestId('discovery-network-toggle'));

    const details = screen.getAllByTestId('discovery-request-detail').map((n) => n.textContent);
    expect(details).toEqual(['2.0 KB', '1.5 KB — no job postings in it', '90.0 KB — 12 job postings']);
  });

  it('blames our own ceiling for an oversize body, not the board', async () => {
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
    await userEvent.click(screen.getByTestId('discovery-network-toggle'));
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
