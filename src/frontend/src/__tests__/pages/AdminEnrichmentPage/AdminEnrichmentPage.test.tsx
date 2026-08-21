import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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
  sweOpenTotal: 8126,
  sweSubcategorized: 4000,
  sweSubcategoryLabelled: 3200,
  subcategoryUnknownSlugs: 0,
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
    // ⚠ The producer key. `scoring.py::to_dict` emits `judge_kappa_prejudge`;
    // the old fixture said `judge_kappa`, which is exactly what masked the
    // panel's always-'—' κ tile for the life of that tile.
    judge_kappa_prejudge: 0.2477,
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
      subcategories: null,
      subcategoryConfidence: null,
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
      humanDecision: null,
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
      url: 'https://example.com/j-2',
      enrichmentStatus: 'done',
      category: 'software_engineering',
      level: 'senior',
      subcategories: ['backend', 'full_stack'],
      subcategoryConfidence: 0.82,
      tags: ['python', 'kubernetes'],
      classifyConfidence: 0.94,
      classifyReasoning: 'Kubernetes platform ownership implies senior IC scope.',
      judged: true,
      judgePassed: true,
      judgeConfidence: 0.9,
      judgeNotes: 'Senior fits: owns platform roadmap.',
      taxonomyVersion: 'v2+abc',
      needsHuman: false,
      humanCorrectedAt: null,
      humanDecision: null,
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
  subcategories: [
    { slug: 'backend', label: 'Backend', sortOrder: 1, parentSlug: 'software_engineering' },
    { slug: 'frontend', label: 'Frontend', sortOrder: 6, parentSlug: 'software_engineering' },
    { slug: 'full_stack', label: 'Full Stack', sortOrder: 7, parentSlug: 'software_engineering' },
  ],
};

function routedFetch(
  overrides: {
    health?: unknown;
    reenrichStatus?: number;
    confirmStatus?: number;
    needsHumanBody?: unknown;
    recentBody?: unknown;
    settingsBody?: unknown;
  } = {}
) {
  return (input: unknown) => {
    const url = input instanceof Request ? input.url : String(input);
    // Confirm POST (…/enrichment/jobs/{sourceId}/{jobListingId}/confirm). Checked
    // before the substring routes below (none of which match ``/confirm``).
    if (url.includes('/confirm')) {
      const status = overrides.confirmStatus ?? 200;
      if (status >= 400) {
        return Promise.resolve(jsonResponse({ detail: 'Confirm failed on the backend' }, status));
      }
      return Promise.resolve(jsonResponse({}));
    }
    // Re-enrich POST (…/enrichment/jobs/{sourceId}/{jobListingId}/reenrich).
    // Default success returns a 200 (identical to the catch-all fall-through);
    // a ``reenrichStatus`` >= 400 drives the failure path so the table's error
    // Alert surfaces.
    if (url.includes('/reenrich')) {
      const status = overrides.reenrichStatus ?? 200;
      if (status >= 400) {
        return Promise.resolve(
          jsonResponse({ detail: 'Re-enrich failed on the backend' }, status)
        );
      }
      return Promise.resolve(jsonResponse({}));
    }
    if (url.includes('/enrichment/health')) {
      return Promise.resolve(jsonResponse(overrides.health ?? HEALTHY_BODY));
    }
    if (url.includes('/enrichment/ticks')) {
      return Promise.resolve(jsonResponse(TICKS_BODY));
    }
    if (url.includes('/enrichment/needs-human')) {
      return Promise.resolve(jsonResponse(overrides.needsHumanBody ?? NEEDS_HUMAN_BODY));
    }
    if (url.includes('/enrichment/recent')) {
      return Promise.resolve(jsonResponse(overrides.recentBody ?? RECENT_BODY));
    }
    if (url.includes('/jobs/facets')) {
      return Promise.resolve(jsonResponse(FACETS_BODY));
    }
    if (url.includes('/admin/settings')) {
      return Promise.resolve(
        jsonResponse(
          overrides.settingsBody ?? {
            settings: [
              {
                key: 'swe_subcategories_enabled',
                value: false,
                updatedAt: null,
                updatedBy: null,
              },
            ],
          }
        )
      );
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
    const queueRow = screen.getByText('Growth Marketing Lead').closest('tr') as HTMLElement;
    await user.click(within(queueRow).getByRole('button', { name: 'Correct' }));

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

  // ── ADM-11: the coverage tile and the reveal switch ─────────────────────

  it('renders the coverage percentage and the meta line', async () => {
    renderPage();
    // 4000 / 8126 = 49.2%
    expect(await screen.findByText('49.2%')).toBeInTheDocument();
    expect(
      screen.getByText(/4,000 of 8,126 OPEN SWE rows evaluated/)
    ).toBeInTheDocument();
  });

  it('⚠ renders an em dash, never NaN, when sweOpenTotal is 0', async () => {
    fetchMock.mockImplementation(
      routedFetch({ health: { ...HEALTHY_BODY, sweOpenTotal: 0, sweSubcategorized: 0 } })
    );
    renderPage();

    expect(await screen.findByText('OPEN SWE coverage')).toBeInTheDocument();
    const tile = screen.getByText('OPEN SWE coverage').closest('div') as HTMLElement;
    expect(within(tile).queryByText(/NaN/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/No OPEN software-engineering rows yet/)
    ).toBeInTheDocument();
  });

  it('warns when subcategoryUnknownSlugs is non-zero', async () => {
    fetchMock.mockImplementation(
      routedFetch({ health: { ...HEALTHY_BODY, subcategoryUnknownSlugs: 3 } })
    );
    renderPage();
    expect(
      await screen.findByText(/are not in the taxonomy/)
    ).toBeInTheDocument();
  });

  it('reflects the settings row in the reveal switch and PUTs on toggle', async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Subcategory rollout');
    const toggle = screen.getByLabelText(
      /show the subcategory filter to users/i
    ) as HTMLInputElement;
    expect(toggle.checked).toBe(false);

    await user.click(toggle);

    await waitFor(() => {
      const put = fetchMock.mock.calls.some((call) => {
        const req = call[0];
        return (
          req instanceof Request &&
          req.url.includes('/admin/settings/swe_subcategories_enabled') &&
          req.method === 'PUT'
        );
      });
      expect(put).toBe(true);
    });
  });

  it('shows the switch as ON when the stored value is true', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        settingsBody: {
          settings: [
            {
              key: 'swe_subcategories_enabled',
              value: true,
              updatedAt: '2026-08-20T00:00:00Z',
              updatedBy: 'a@b.c',
            },
          ],
        },
      })
    );
    renderPage();
    await screen.findByText('Subcategory rollout');
    const toggle = screen.getByLabelText(
      /show the subcategory filter to users/i
    ) as HTMLInputElement;
    await waitFor(() => expect(toggle.checked).toBe(true));
  });

  // ── ADM-10: subcategory chips in the recent table's existing Labels cell ─

  it('renders subcategory chips in the recent Labels cell, primary first', async () => {
    renderPage();
    const row = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    // DISPLAY LABELS now, not raw slugs: FE-CT-2 folded
    // FALLBACK_SUBCATEGORIES into FACET_LABELS, so the chips resolve. This is
    // the assertion the phase-1 test said would replace it.
    expect(within(row).getByText('Backend')).toBeInTheDocument();
    expect(within(row).getByText('Full Stack')).toBeInTheDocument();
  });

  it('renders no subcategory chips for a null row and does not throw', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        recentBody: {
          rows: [{ ...RECENT_BODY.rows[0], subcategories: null }],
        },
      })
    );
    renderPage();
    const row = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    expect(within(row).queryByText('Backend')).not.toBeInTheDocument();
    expect(within(row).getByText('Senior')).toBeInTheDocument();
  });

  it('⚠ the recent expander still spans the full head row — NO column was added', async () => {
    // Subcategory chips reuse the existing Labels cell, so colSpan={7} is
    // correct as-is. This pins that so nobody "fixes" it to 8.
    const user = userEvent.setup();
    renderPage();

    const row = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Expand reasoning' }));

    const table = row.closest('table') as HTMLElement;
    const headCells = table.querySelectorAll('thead tr th');
    const expanderCell = table.querySelector('tbody td[colspan]') as HTMLElement;
    expect(expanderCell.getAttribute('colspan')).toBe(String(headCells.length));
  });

  // ── ADM-9: sortable headers + subcategory filters on the triage queue ────

  function lastNeedsHumanUrl(mock: ReturnType<typeof vi.fn>): string {
    const urls = mock.mock.calls
      .map((call) => (call[0] instanceof Request ? call[0].url : String(call[0])))
      .filter((url) => url.includes('/enrichment/needs-human'));
    return urls[urls.length - 1] ?? '';
  }

  it('clicking Confidence sorts desc, clicking again flips to asc — both reset offset', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Growth Marketing Lead');

    await user.click(screen.getByRole('button', { name: 'Confidence' }));
    await waitFor(() => {
      const url = lastNeedsHumanUrl(fetchMock);
      expect(url).toContain('sort=classify_confidence');
      expect(url).toContain('sortDir=desc');
      expect(url).toContain('offset=0');
    });

    await user.click(screen.getByRole('button', { name: 'Confidence' }));
    await waitFor(() => {
      const url = lastNeedsHumanUrl(fetchMock);
      expect(url).toContain('sort=classify_confidence');
      expect(url).toContain('sortDir=asc');
      expect(url).toContain('offset=0');
    });
  });

  it('sorts by the Sub conf. column', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Growth Marketing Lead');

    await user.click(screen.getByRole('button', { name: 'Sub conf.' }));
    await waitFor(() => {
      expect(lastNeedsHumanUrl(fetchMock)).toContain('sort=subcategory_confidence');
    });
  });

  it('selecting a proposed subcategory issues subcategory=backend', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Growth Marketing Lead');

    await user.click(screen.getByRole('combobox', { name: 'Proposed subcategory' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Backend' }));

    await waitFor(() => {
      expect(lastNeedsHumanUrl(fetchMock)).toContain('subcategory=backend');
    });
  });

  it('selecting the Unlabelled SWE lens issues subcategoryState', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Growth Marketing Lead');

    await user.click(screen.getByRole('combobox', { name: 'Subcategory state' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Unlabelled SWE' }));

    await waitFor(() => {
      expect(lastNeedsHumanUrl(fetchMock)).toContain('subcategoryState=unlabelled_swe');
    });
  });

  it('⚠ the queue expander still spans the FULL head row after the column bump', async () => {
    // The head row went 6 cells -> 7. A stale colSpan={6} leaves the expander
    // short of the full width, which looks like a rendering bug and is one.
    const user = userEvent.setup();
    renderPage();

    const row = (await screen.findByText('Growth Marketing Lead')).closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Expand details' }));

    const table = row.closest('table') as HTMLElement;
    const headCells = table.querySelectorAll('thead tr th');
    const expanderCell = table.querySelector('tbody td[colspan]') as HTMLElement;
    expect(expanderCell.getAttribute('colspan')).toBe(String(headCells.length));
  });

  it('renders subcategory chips in the queue Proposed cell, primary first', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        needsHumanBody: {
          ...NEEDS_HUMAN_BODY,
          rows: [
            {
              ...NEEDS_HUMAN_BODY.rows[0],
              category: 'software_engineering',
              subcategories: ['backend', 'full_stack'],
              subcategoryConfidence: 0.77,
            },
          ],
        },
      })
    );
    renderPage();

    const row = (await screen.findByText('Growth Marketing Lead')).closest(
      'tr'
    ) as HTMLElement;
    // Chips render `FACET_LABELS[slug] ?? slug`, and FE-CT-2 folded
    // FALLBACK_SUBCATEGORIES into FACET_LABELS — so the display labels resolve
    // and the raw-slug fallback is no longer reached for a known slug.
    expect(within(row).getByText('Backend')).toBeInTheDocument();
    expect(within(row).getByText('Full Stack')).toBeInTheDocument();
    expect(within(row).getByText('0.77')).toBeInTheDocument();
  });

  it('renders no subcategory chips and does not throw when the row is null', async () => {
    renderPage();
    const row = (await screen.findByText('Growth Marketing Lead')).closest(
      'tr'
    ) as HTMLElement;
    // The default fixture row is `subcategories: null`.
    expect(within(row).queryByText('Backend')).not.toBeInTheDocument();
    // Sub conf. renders the em-dash placeholder rather than crashing.
    expect(within(row).getAllByText('—').length).toBeGreaterThan(0);
  });

  // ── ADM-8: the ordered subcategory control inside CorrectionDialog ───────

  it('shows the subcategory control only for a SWE row', async () => {
    const user = userEvent.setup();
    renderPage();

    // The queue row is `growth` — no control.
    const queueRow = (await screen.findByText('Growth Marketing Lead')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(queueRow).getByRole('button', { name: 'Correct' }));
    expect(await screen.findByText('Correct labels')).toBeInTheDocument();
    expect(
      screen.queryByRole('combobox', { name: /subcategories/i })
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    // The recent row is `software_engineering` — control present, pre-filled.
    const recentRow = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: 'Correct' }));
    expect(await screen.findByText('Correct labels')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /subcategories/i })).toBeInTheDocument();
  });

  it('offers subcategory options from LIVE facets, not a fallback constant', async () => {
    const user = userEvent.setup();
    renderPage();

    const recentRow = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: 'Correct' }));
    await screen.findByText('Correct labels');

    await user.click(screen.getByRole('combobox', { name: /subcategories/i }));
    const options = await screen.findAllByRole('option');
    // Exactly the three FACETS_BODY offers — a fallback constant would carry 15.
    expect(options.map((o) => o.textContent)).toEqual([
      'Backend',
      'Frontend',
      'Full Stack',
    ]);
  });

  it('⚠ changing category to non-SWE CLEARS the control and OMITS the key', async () => {
    // Two failures in one test. Leaving the selection behind would post
    // subcategories under a category that cannot carry them (a 409). Sending
    // `[]` instead of omitting the key would be an INSTRUCTION — "evaluated,
    // nothing applies" — from a dialog that stopped showing the control.
    const user = userEvent.setup();
    renderPage();

    const recentRow = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: 'Correct' }));
    await screen.findByText('Correct labels');
    expect(screen.getByRole('combobox', { name: /subcategories/i })).toBeInTheDocument();

    await user.click(screen.getByRole('combobox', { name: 'Category' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Growth' }));

    expect(
      screen.queryByRole('combobox', { name: /subcategories/i })
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Save correction' }));

    let call: [unknown, unknown] | undefined;
    await waitFor(() => {
      call = fetchMock.mock.calls.find((c) => {
        const req = c[0];
        return (
          req instanceof Request &&
          req.url.includes('/enrichment/jobs/greenhouse_api/j-2/correct') &&
          req.method === 'POST'
        );
      }) as [unknown, unknown] | undefined;
      expect(call).toBeDefined();
    });

    const body = (await (call![0] as Request).clone().json()) as Record<string, unknown>;
    expect('subcategories' in body).toBe(false);
  });

  it('posts the ORDERED subcategory array for a SWE row', async () => {
    const user = userEvent.setup();
    renderPage();

    const recentRow = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: 'Correct' }));
    await screen.findByText('Correct labels');

    await user.click(screen.getByRole('button', { name: 'Save correction' }));

    let call: [unknown, unknown] | undefined;
    await waitFor(() => {
      call = fetchMock.mock.calls.find((c) => {
        const req = c[0];
        return (
          req instanceof Request &&
          req.url.includes('/enrichment/jobs/greenhouse_api/j-2/correct') &&
          req.method === 'POST'
        );
      }) as [unknown, unknown] | undefined;
      expect(call).toBeDefined();
    });

    const body = (await (call![0] as Request).clone().json()) as {
      subcategories?: string[];
    };
    expect(body.subcategories).toEqual(['backend', 'full_stack']);
  });

  // ── The NEVER-EVALUATED SWE row (`subcategories: null`) ──────────────────
  //
  // ⚠ THE WORST BUG THIS DIALOG CAN CAUSE. `useState(row.subcategories ?? [])`
  // collapses `null` (never evaluated) into `[]`, and `[]` on the wire is the
  // TERMINAL assertion "evaluated, nothing applies" + `source='human'`. That
  // combination permanently ejects the row from the backfill queue — the
  // backend's `apply_subcategory_result` skips `source='human'`, and
  // `apply_result`'s per-field unlock only fires while the array IS NULL. It
  // also counts the row in `sweSubcategorized`, the numerator the 90% reveal
  // is read off, so it corrupts the label AND inflates the metric that decides
  // whether to ship. Phase 1 makes it acute: `job_subcategories` ships EMPTY,
  // so the picker has ZERO options and an admin fixing a LEVEL cannot even see
  // a subcategory, yet every save would assert one.
  const SWE_NULL_RECENT = {
    ...RECENT_BODY,
    rows: [{ ...RECENT_BODY.rows[0], subcategories: null, subcategoryConfidence: null }],
  };

  async function postedCorrectionBody(): Promise<Record<string, unknown>> {
    let call: [unknown, unknown] | undefined;
    await waitFor(() => {
      call = fetchMock.mock.calls.find((c) => {
        const req = c[0];
        return (
          req instanceof Request &&
          req.url.includes('/enrichment/jobs/greenhouse_api/j-2/correct') &&
          req.method === 'POST'
        );
      }) as [unknown, unknown] | undefined;
      expect(call).toBeDefined();
    });
    return (await (call![0] as Request).clone().json()) as Record<string, unknown>;
  }

  it('⚠ OMITS the key on a SWE row whose array is null and the picker untouched', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(routedFetch({ recentBody: SWE_NULL_RECENT }));
    renderPage();

    const recentRow = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: 'Correct' }));
    await screen.findByText('Correct labels');
    // The control IS shown (the row is SWE) — showing it is not touching it.
    expect(screen.getByRole('combobox', { name: /subcategories/i })).toBeInTheDocument();

    // A LEVEL-ONLY correction, the exact case that must not assert anything
    // about specialties.
    await user.click(screen.getByRole('combobox', { name: 'Level' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Mid' }));

    await user.click(screen.getByRole('button', { name: 'Save correction' }));

    const body = await postedCorrectionBody();
    expect(body.level).toBe('mid');
    expect('subcategories' in body).toBe(false);
  });

  it('SENDS the key on a null-array SWE row once the picker is touched', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(routedFetch({ recentBody: SWE_NULL_RECENT }));
    renderPage();

    const recentRow = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: 'Correct' }));
    await screen.findByText('Correct labels');

    await user.click(screen.getByRole('combobox', { name: /subcategories/i }));
    const options = await screen.findAllByRole('option');
    await user.click(options.find((o) => o.textContent === 'Backend')!);

    await user.click(screen.getByRole('button', { name: 'Save correction' }));

    const body = await postedCorrectionBody();
    expect(body.subcategories).toEqual(['backend']);
  });

  it('CLEARING an existing selection to [] is an explicit terminal decision', async () => {
    // The other side of the same rule: `[]` must still be reachable. Emptying
    // the picker on a row that HAD labels is a real human judgement ("I looked;
    // none apply") and has to survive as `[]`, not be swallowed as untouched.
    const user = userEvent.setup();
    renderPage();

    const recentRow = (await screen.findByText('Senior Platform Engineer')).closest(
      'tr'
    ) as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: 'Correct' }));
    await screen.findByText('Correct labels');

    const combobox = screen.getByRole('combobox', { name: /subcategories/i });
    await user.click(combobox);
    const options = await screen.findAllByRole('option');
    // Untick both pre-filled slugs.
    await user.click(options.find((o) => o.textContent === 'Backend')!);
    await user.click(
      (await screen.findAllByRole('option')).find((o) => o.textContent === 'Full Stack')!
    );
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: 'Save correction' }));

    const body = await postedCorrectionBody();
    expect(body.subcategories).toEqual([]);
  });

  it('expands a recent row to reveal the judge notes and classifier reasoning', async () => {
    const user = userEvent.setup();
    renderPage();

    const title = await screen.findByText('Senior Platform Engineer');
    const row = title.closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Expand reasoning' }));

    expect(
      await screen.findByText(/Kubernetes platform ownership implies senior IC scope/)
    ).toBeInTheDocument();
    expect(screen.getByText(/Senior fits: owns platform roadmap/)).toBeInTheDocument();
  });

  it('opens the correction dialog from a recent row and posts to that job', async () => {
    const user = userEvent.setup();
    renderPage();

    const title = await screen.findByText('Senior Platform Engineer');
    const row = title.closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Correct' }));

    expect(await screen.findByText('Correct labels')).toBeInTheDocument();
    // The recent row's evidence is shown in the editor too.
    expect(screen.getByText(/Senior fits: owns platform roadmap/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save correction' }));
    await waitFor(() => {
      const posted = fetchMock.mock.calls.some((call) => {
        const req = call[0];
        return (
          req instanceof Request &&
          req.url.includes('/enrichment/jobs/greenhouse_api/j-2/correct') &&
          req.method === 'POST'
        );
      });
      expect(posted).toBe(true);
    });
  });

  it('normalizes tags and nullifies cleared fields in the correction POST body', async () => {
    const user = userEvent.setup();
    renderPage();

    const queueTitle = await screen.findByText('Growth Marketing Lead');
    const queueRow = queueTitle.closest('tr') as HTMLElement;
    await user.click(within(queueRow).getByRole('button', { name: 'Correct' }));

    expect(await screen.findByText('Correct labels')).toBeInTheDocument();

    // Add a messy tag: mixed-case + surrounding whitespace. The Autocomplete
    // onChange runs `map(toLowerCase().trim()).filter(Boolean)`, so it must land
    // in the body lowercased + trimmed (and no blank ever survives).
    const tagInput = screen.getByRole('combobox', { name: 'Tags' });
    await user.type(tagInput, '  DevOps  {Enter}');

    // Clear the Level facet ("All") → it must POST as null.
    await user.click(screen.getByRole('combobox', { name: 'Level' }));
    const levelListbox = await screen.findByRole('listbox');
    await user.click(within(levelListbox).getByRole('option', { name: 'All' }));

    // Note left empty → `note.trim() || null` posts null.
    await user.click(screen.getByRole('button', { name: 'Save correction' }));

    let correctCall: [unknown, unknown] | undefined;
    await waitFor(() => {
      correctCall = fetchMock.mock.calls.find((call) => {
        const req = call[0];
        return (
          req instanceof Request &&
          req.url.includes('/enrichment/jobs/greenhouse_api/j-1/correct') &&
          req.method === 'POST'
        );
      }) as [unknown, unknown] | undefined;
      expect(correctCall).toBeDefined();
    });

    const body = (await (correctCall![0] as Request).clone().json()) as {
      category: string | null;
      level: string | null;
      tags: string[];
      note: string | null;
    };

    // Tags: pre-existing sql/ab-testing preserved, the new tag lowercased +
    // trimmed, and every entry is non-blank + already-normalized.
    expect(body.tags).toContain('devops');
    expect(body.tags).toContain('sql');
    expect(body.tags).toContain('ab-testing');
    expect(body.tags.every((t) => t.length > 0 && t === t.toLowerCase().trim())).toBe(true);

    // Cleared level → null; untouched category stays 'growth'; empty note → null.
    expect(body.level).toBeNull();
    expect(body.category).toBe('growth');
    expect(body.note).toBeNull();
  });

  // ── Re-enrich error surfacing (Round-1 I1 deliverable) ───────────────────
  // A failed re-enrich must be visible (``.unwrap()`` + try/catch → error
  // Alert), not fire-and-forget. Regressing to silent failure must break a test.

  it('surfaces an error Alert when a needs-human re-enrich fails', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(routedFetch({ reenrichStatus: 500 }));
    renderPage();

    const queueTitle = await screen.findByText('Growth Marketing Lead');
    const queueRow = queueTitle.closest('tr') as HTMLElement;
    await user.click(within(queueRow).getByRole('button', { name: /re-enrich/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/Re-enrich failed on the backend/);
  });

  it('surfaces an error Alert when a recent-row re-enrich fails', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(routedFetch({ reenrichStatus: 500 }));
    renderPage();

    const recentTitle = await screen.findByText('Senior Platform Engineer');
    const recentRow = recentTitle.closest('tr') as HTMLElement;
    await user.click(within(recentRow).getByRole('button', { name: /re-enrich/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/Re-enrich failed on the backend/);
  });

  it('shows no error Alert when a needs-human re-enrich succeeds', async () => {
    const user = userEvent.setup();
    renderPage(); // default routedFetch → re-enrich returns 200

    const queueTitle = await screen.findByText('Growth Marketing Lead');
    const queueRow = queueTitle.closest('tr') as HTMLElement;
    await user.click(within(queueRow).getByRole('button', { name: /re-enrich/i }));

    // Wait for the re-enrich POST to have fired, then assert no error surfaced.
    await waitFor(() => {
      const posted = fetchMock.mock.calls.some((call) => {
        const req = call[0];
        return req instanceof Request && req.url.includes('/reenrich') && req.method === 'POST';
      });
      expect(posted).toBe(true);
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  // ── Confirm (one-click "this is correct") ────────────────────────────────

  it('confirms a queue row in one click, posting to the confirm endpoint', async () => {
    const user = userEvent.setup();
    renderPage();

    const queueTitle = await screen.findByText('Growth Marketing Lead');
    const queueRow = queueTitle.closest('tr') as HTMLElement;
    await user.click(within(queueRow).getByRole('button', { name: 'Confirm' }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.some((call) => {
        const req = call[0];
        return (
          req instanceof Request &&
          req.url.includes('/enrichment/jobs/greenhouse_api/j-1/confirm') &&
          req.method === 'POST'
        );
      });
      expect(posted).toBe(true);
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('disables Confirm on a queue row with no proposed labels', async () => {
    const noProposalBody = {
      ...NEEDS_HUMAN_BODY,
      rows: [{ ...NEEDS_HUMAN_BODY.rows[0], category: null, level: null }],
    };
    fetchMock.mockImplementation(routedFetch({ needsHumanBody: noProposalBody }));
    renderPage();

    const queueTitle = await screen.findByText('Growth Marketing Lead');
    const queueRow = queueTitle.closest('tr') as HTMLElement;
    // A demoted row can't be one-click confirmed — the human must open Correct.
    expect(within(queueRow).getByRole('button', { name: 'Confirm' })).toBeDisabled();
  });

  it('surfaces an error Alert when a confirm fails', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(routedFetch({ confirmStatus: 500 }));
    renderPage();

    const queueTitle = await screen.findByText('Growth Marketing Lead');
    const queueRow = queueTitle.closest('tr') as HTMLElement;
    await user.click(within(queueRow).getByRole('button', { name: 'Confirm' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/Confirm failed on the backend/);
  });

  it('renders a "confirmed correct" outcome chip in the recent table', async () => {
    const confirmedRecent = {
      rows: [
        {
          ...RECENT_BODY.rows[0],
          humanCorrectedAt: '2026-07-09T01:00:00Z',
          humanDecision: 'confirmed_correct',
        },
      ],
    };
    fetchMock.mockImplementation(routedFetch({ recentBody: confirmedRecent }));
    renderPage();

    expect(await screen.findByText('confirmed correct')).toBeInTheDocument();
  });
});
