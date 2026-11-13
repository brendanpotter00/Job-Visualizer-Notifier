import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { JustPostedSection } from '../../../pages/LandingPage/sections/JustPostedSection';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { logger } from '../../../lib/logger';
import type { Job } from '../../../types';
import {
  buildHolidayLandingJobs,
  buildRichLandingJobs,
  LANDING_NOW,
  SEARCH_META,
  simulateSearchParams,
  toBackendRow,
} from './landingJobFixtures';

const CONTENT = LANDING_CONTENT.freshJobs;

interface Reply {
  status?: number;
  reject?: unknown;
  pending?: boolean;
}

let corpus: Job[];
let reply: (call: number) => Reply;
const originalFetch = globalThis.fetch;

function installFetch() {
  let call = 0;
  const fetchMock = vi.fn((input: unknown, _init?: RequestInit) => {
    const url = String(input);
    if (!url.startsWith('/api/jobs/search?')) {
      throw new Error(`unexpected fetch URL in JustPostedSection test: ${url}`);
    }
    call += 1;
    const { status = 200, reject, pending } = reply(call);
    if (pending) return new Promise<never>(() => {});
    if (reject !== undefined) return Promise.reject(reject);
    const params = new URLSearchParams(url.slice(url.indexOf('?') + 1));
    const body = {
      jobs: simulateSearchParams(corpus, params).map(toBackendRow),
      nextCursor: null,
      meta: SEARCH_META,
    };
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => body,
      text: async () => JSON.stringify(body),
    });
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(LANDING_NOW);
  corpus = buildRichLandingJobs(LANDING_NOW);
  reply = () => ({});
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

function renderSection() {
  const fetchMock = installFetch();
  const view = renderWithProviders(
    <div data-testid="host">
      <JustPostedSection content={CONTENT} />
    </div>,
    { initialEntries: ['/'] }
  );
  return { ...view, fetchMock, host: screen.getByTestId('host') };
}

describe('JustPostedSection', () => {
  it('shows a same-shape skeleton while the jobs load', async () => {
    reply = () => ({ pending: true });
    const { fetchMock } = renderSection();

    expect(screen.getByRole('status', { name: CONTENT.loadingLabel })).toBeInTheDocument();
    const skeleton = screen.getByTestId('fresh-jobs-skeleton');
    expect(within(skeleton).getAllByTestId('fresh-jobs-skeleton-slot')).toHaveLength(3);
    expect(within(skeleton).getByText(CONTENT.heading)).toBeInTheDocument();
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fresh-jobs-triptych')).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });

  it('swaps in the triptych: three full slots under the section heading', async () => {
    const { fetchMock } = renderSection();

    const triptych = await screen.findByTestId('fresh-jobs-triptych');
    expect(within(triptych).getByRole('heading', { level: 2 })).toHaveTextContent(CONTENT.heading);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    for (const slot of ['early_career', 'last_24h', 'big_tech']) {
      const region = within(triptych).getByTestId(`triptych-slot-${slot}`);
      expect(region.querySelectorAll('[data-flip-role="sizer"]')).toHaveLength(15);
    }
    expect(within(triptych).getByText('Last 24 hours')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const [, init] of fetchMock.mock.calls) {
      expect(init?.headers).toBeUndefined();
    }
  });

  it('names the window it widened to on a quiet week', async () => {
    corpus = buildHolidayLandingJobs(LANDING_NOW);
    renderSection();

    const triptych = await screen.findByTestId('fresh-jobs-triptych');
    expect(within(triptych).getByText('Last 3 days')).toBeInTheDocument();
    expect(within(triptych).queryByText('Last 24 hours')).not.toBeInTheDocument();
  });

  it('an empty slot gets its empty text while the others still show jobs', async () => {
    corpus = buildHolidayLandingJobs(LANDING_NOW).filter(
      (job) => job.level !== 'intern' && job.level !== 'new_grad'
    );
    renderSection();

    const triptych = await screen.findByTestId('fresh-jobs-triptych');
    const early = within(triptych).getByTestId('triptych-slot-early_career');
    expect(early).toHaveAttribute('data-empty', 'true');
    expect(within(early).getByText('None in the last 60 days.')).toBeInTheDocument();
    expect(within(triptych).getByText('Last 3 days')).toBeInTheDocument();
  });

  it.each([
    ['one request answers 500', (call: number): Reply => (call === 2 ? { status: 500 } : {})],
    [
      'one request never reaches the server',
      (call: number): Reply => (call === 3 ? { reject: new TypeError('network down') } : {}),
    ],
  ])('renders nothing at all when %s', async (_name, failing) => {
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    reply = failing;
    const { host, fetchMock } = renderSection();

    expect(screen.getByRole('status', { name: CONTENT.loadingLabel })).toBeInTheDocument();
    await waitFor(() => expect(host).toBeEmptyDOMElement());
    expect(screen.queryByText(CONTENT.heading)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(logged).toHaveBeenCalled();
  });

  it('renders nothing at all when every slot comes back empty', async () => {
    corpus = [];
    const { host, fetchMock } = renderSection();

    await waitFor(() => expect(host).toBeEmptyDOMElement());
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
