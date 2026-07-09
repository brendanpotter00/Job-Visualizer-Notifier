import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { AdminEnrichmentPage } from '../../../pages/AdminEnrichmentPage/AdminEnrichmentPage';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// URLs. Shim the global to resolve them against a test origin — same approach
// as AdminLocationNormalizationPage.test.tsx.
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
    reducer: {
      [adminApi.reducerPath]: adminApi.reducer,
      [jobsApi.reducerPath]: jobsApi.reducer,
    },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: {
          extraArgument: { getTokenOrNull: () => Promise.resolve('test-token') },
        },
      })
        .concat(adminApi.middleware)
        .concat(jobsApi.middleware),
  });
}

function renderPage() {
  return render(
    <Provider store={makeStore()}>
      <AdminEnrichmentPage />
    </Provider>
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const HEALTHY_BODY = {
  schemaPresent: true,
  enabled: true,
  openByStatus: { unenriched: 100, claimed: 5, done: 40, needs_human: 2 },
  eligibleUnenriched: 80,
  staleClaims: 0,
  claimTtlMinutes: 240,
  needsHumanOpen: 2,
  humanCorrectedTotal: 1,
  lastEnrichedAt: '2026-07-09T00:00:00Z',
  lastEnrichedAgeS: 120,
  lastTickUuid: 'tick-1',
  lastTickStatus: 'ok',
  lastTickStartedAt: '2026-07-09T00:00:00Z',
  lastTickAgeS: 300,
  lastTickDriftSuspected: false,
  windowHours: 24,
  enrichedInWindow: 96,
  errorTicksInWindow: 0,
};

const TICKS_BODY = {
  ticks: [
    {
      tickUuid: 'tick-0',
      startedAt: '2026-07-08T22:00:00Z',
      endedAt: '2026-07-08T22:05:00Z',
      status: 'ok',
      notes: null,
      claimed: 12,
      cleaned: 12,
      classified: 12,
      judged: 3,
      corrected: 1,
      needsHuman: 1,
      sent: 12,
      errors: 0,
      nulledFacets: 0,
      durationS: 300,
      taxonomyVersion: 'v2+abc',
      stageTimings: [{ stage: 'classify', ms: 90000, items: 12, retries: 0 }],
      heartbeatAgeS: 30,
      driftSuspected: false,
      receivedAt: '2026-07-08T22:05:01Z',
    },
    {
      tickUuid: 'tick-1',
      startedAt: '2026-07-09T00:00:00Z',
      endedAt: null,
      status: 'error',
      notes: 'write-back failed',
      claimed: 12,
      cleaned: 12,
      classified: 12,
      judged: 0,
      corrected: 0,
      needsHuman: 0,
      sent: 0,
      errors: 12,
      nulledFacets: 0,
      durationS: null,
      taxonomyVersion: 'v2+abc',
      stageTimings: [],
      heartbeatAgeS: 10,
      driftSuspected: false,
      receivedAt: '2026-07-09T00:00:01Z',
    },
  ],
  windowHours: 24,
  latestScorecard: {
    n: 252,
    gold_quality: 'draft',
    category_accuracy: 0.9087,
    category_f1_macro: 0.9152,
    level_exact_accuracy: 0.7897,
    level_filter_consistent_accuracy: 0.8214,
    tags_f1: 0.2159,
    tags_token_f1: 0.289,
    judge_kappa: 0.2477,
  },
  latestScorecardTickUuid: 'tick-0',
  latestKnobs: { judge_scope: 'low_confidence' },
};

const NEEDS_HUMAN_BODY = {
  rows: [
    {
      sourceId: 'greenhouse_api',
      jobListingId: 'j-1',
      title: 'Growth Marketing Lead',
      company: 'acme',
      url: 'https://example.com/j-1',
      jobStatus: 'OPEN',
      enrichmentStatus: 'done',
      category: 'growth',
      level: 'mid',
      tags: ['sql', 'ab-testing'],
      cleanDescription: 'Own the growth funnel end to end.',
      classifyConfidence: 0.55,
      classifyReasoning: 'Title suggests growth; responsibilities read PM.',
      taxonomyVersion: 'v2+abc',
      judged: true,
      judgePassed: false,
      judgeConfidence: 0.5,
      judgeNotes: 'Ambiguous between growth and product_manager.',
      enrichedAt: '2026-07-09T00:00:00Z',
      humanCorrectedAt: null,
      humanCorrectedBy: null,
    },
  ],
  total: 1,
  limit: 10,
  offset: 0,
};

const RECENT_BODY = {
  rows: [
    {
      sourceId: 'greenhouse_api',
      jobListingId: 'j-2',
      title: 'Senior Platform Engineer',
      company: 'acme',
      enrichmentStatus: 'done',
      category: 'software_engineering',
      level: 'senior',
      tags: ['python', 'kubernetes'],
      classifyConfidence: 0.94,
      judged: true,
      judgePassed: true,
      needsHuman: false,
      humanCorrectedAt: null,
      enrichedAt: '2026-07-09T00:00:00Z',
    },
  ],
};

const FACETS_BODY = {
  categories: [
    { slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0, parentSlug: null },
    { slug: 'growth', label: 'Growth', sortOrder: 4, parentSlug: null },
  ],
  levels: [
    { slug: 'new_grad', label: 'New Grad', sortOrder: 0, parentSlug: 'entry' },
    { slug: 'entry', label: 'Entry', sortOrder: 1, parentSlug: null },
    { slug: 'mid', label: 'Mid', sortOrder: 2, parentSlug: null },
  ],
};

function routedFetch(overrides: { health?: unknown } = {}) {
  return (input: unknown) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes('/enrichment/health')) {
      return Promise.resolve(jsonResponse(overrides.health ?? HEALTHY_BODY));
    }
    if (url.includes('/enrichment/ticks')) {
      return Promise.resolve(jsonResponse(TICKS_BODY));
    }
    if (url.includes('/enrichment/needs-human')) {
      return Promise.resolve(jsonResponse(NEEDS_HUMAN_BODY));
    }
    if (url.includes('/enrichment/recent')) {
      return Promise.resolve(jsonResponse(RECENT_BODY));
    }
    if (url.includes('/jobs/facets')) {
      return Promise.resolve(jsonResponse(FACETS_BODY));
    }
    return Promise.resolve(jsonResponse({}));
  };
}

describe('AdminEnrichmentPage', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(routedFetch());
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders the full healthy dashboard: verdict, funnel, ticks, scorecard, queue, recent', async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('HEALTHY')).toBeInTheDocument();
    });

    // Funnel legend + claimable split.
    expect(screen.getByText(/Unenriched 100/)).toBeInTheDocument();
    expect(screen.getByText(/Of the unenriched: 80 claimable/)).toBeInTheDocument();

    // Tick strip caption reflects both ticks.
    expect(screen.getByText(/2 tick\(s\) \/ 24h/)).toBeInTheDocument();

    // Scorecard: primary level metric + draft-gold advisory chip.
    expect(screen.getByText('Level (filter-consistent)')).toBeInTheDocument();
    expect(screen.getByText('82.1%')).toBeInTheDocument();
    expect(screen.getByText(/gold labels: draft/)).toBeInTheDocument();

    // Needs-human queue row + recent enrichments row (their queries resolve
    // after the top slots, so await them).
    expect(await screen.findByText('Growth Marketing Lead')).toBeInTheDocument();
    expect(await screen.findByText('Senior Platform Engineer')).toBeInTheDocument();
  });

  it('renders the DARK verdict when the laptop goes quiet with backlog waiting', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        health: { ...HEALTHY_BODY, lastTickAgeS: 999999, lastEnrichedAgeS: 999999 },
      })
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('DARK')).toBeInTheDocument();
    });
    expect(screen.getByText(/gone dark/)).toBeInTheDocument();
  });

  it('renders IDLE when the kill switch is off', async () => {
    fetchMock.mockImplementation(routedFetch({ health: { ...HEALTHY_BODY, enabled: false } }));
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('IDLE')).toBeInTheDocument();
    });
  });

  it('opens the correction dialog pre-filled from the queue row', async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Growth Marketing Lead')).toBeInTheDocument();
    });
    await user.click(screen.getByRole('button', { name: 'Correct' }));

    expect(await screen.findByText('Correct labels')).toBeInTheDocument();
    // Judge evidence shown in the editor.
    expect(screen.getByText(/Ambiguous between growth and product_manager/)).toBeInTheDocument();
    // Save posts to the correct endpoint.
    await user.click(screen.getByRole('button', { name: 'Save correction' }));
    await waitFor(() => {
      const posted = fetchMock.mock.calls.some((call) => {
        const req = call[0];
        return (
          req instanceof Request &&
          req.url.includes('/enrichment/jobs/greenhouse_api/j-1/correct') &&
          req.method === 'POST'
        );
      });
      expect(posted).toBe(true);
    });
  });
});
