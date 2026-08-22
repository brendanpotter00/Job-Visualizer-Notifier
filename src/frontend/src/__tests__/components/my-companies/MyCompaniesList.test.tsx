import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesList } from '../../../components/my-companies/MyCompaniesList';
import type { UserCompany } from '../../../features/userCompanies/userCompaniesApi';

// `fetchBaseQuery` builds relative URLs, which Node's `Request` rejects.
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
function noContentResponse(): Response {
  return new Response(null, { status: 204 });
}

const COMPANY_A: UserCompany = {
  id: 'u-aaaaaaaaaa',
  displayName: 'Duolingo',
  ats: 'greenhouse',
  boardToken: 'duolingo',
  sourceId: 'custom:u-aaaaaaaaaa',
  healthState: 'unverified',
  openJobCount: 0,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

const COMPANY_B: UserCompany = {
  id: 'u-bbbbbbbbbb',
  displayName: 'Ramp',
  ats: 'ashby',
  boardToken: 'ramp',
  sourceId: 'custom:u-bbbbbbbbbb',
  healthState: 'unverified',
  openJobCount: 42,
  lastSuccessAt: '2026-08-09T10:00:00Z',
  trackingStartedAt: null,
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MyCompaniesList', () => {
  it('renders each company with a health badge, open-job count, and last-checked', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ companies: [COMPANY_A, COMPANY_B] }));
    renderWithProviders(<MyCompaniesList />);

    const rows = await screen.findAllByTestId('my-company-row');
    expect(rows).toHaveLength(2);

    // Company A: unverified badge, 0 open jobs, never checked.
    const rowA = rows[0];
    expect(within(rowA).getByText('Duolingo')).toBeInTheDocument();
    expect(within(rowA).getByText('Successfully tracking')).toBeInTheDocument();
    expect(within(rowA).getByText(/0 open jobs/i)).toBeInTheDocument();
    expect(within(rowA).getByText(/not yet checked/i)).toBeInTheDocument();
    // Links to the private trend page by runtime id.
    expect(within(rowA).getByTestId('my-company-link')).toHaveAttribute(
      'href',
      '/add-companies/u-aaaaaaaaaa'
    );

    // Company B: has a job count and a last-checked timestamp.
    const rowB = rows[1];
    expect(within(rowB).getByText(/42 open jobs/i)).toBeInTheDocument();
    expect(within(rowB).getByText(/last checked/i)).toBeInTheDocument();
  });

  it('shows an empty state when the user tracks nothing', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ companies: [] }));
    renderWithProviders(<MyCompaniesList />);

    expect(await screen.findByText(/no companies yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('my-company-row')).not.toBeInTheDocument();
  });

  it('removes a company via the confirm dialog', async () => {
    // First load returns one company; the DELETE resolves 204; the invalidation
    // refetch returns an empty list.
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const req = input as Request;
      if (req.method === 'DELETE') return noContentResponse();
      return jsonResponse({ companies: [COMPANY_A] });
    });
    const user = userEvent.setup();
    renderWithProviders(<MyCompaniesList />);

    await screen.findByTestId('my-company-row');
    await user.click(screen.getByTestId('my-company-remove'));

    // A confirm dialog gates the destructive action.
    const confirm = await screen.findByTestId('my-company-remove-confirm');
    await user.click(confirm);

    await waitFor(() => {
      const deleteCall = fetchMock.mock.calls.find(
        ([input]) => (input as Request).method === 'DELETE'
      );
      expect(deleteCall).toBeDefined();
      expect((deleteCall![0] as Request).url).toMatch(/\/api\/users\/companies\/u-aaaaaaaaaa$/);
    });
  });

  it('does not fire the delete when the dialog is cancelled', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ companies: [COMPANY_A] }));
    const user = userEvent.setup();
    renderWithProviders(<MyCompaniesList />);

    await screen.findByTestId('my-company-row');
    await user.click(screen.getByTestId('my-company-remove'));
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    const deleteCall = fetchMock.mock.calls.find(
      ([input]) => (input as Request).method === 'DELETE'
    );
    expect(deleteCall).toBeUndefined();
  });

  it('renders a provisional discovering row as a "Setting up…" badge (E7 capture pivot)', async () => {
    const DISCOVERING: UserCompany = {
      id: 'u-discover01',
      displayName: 'careers.acme.example',
      ats: 'discovered',
      boardToken: 'https://careers.acme.example/jobs',
      sourceId: 'custom:u-discover01',
      healthState: 'discovering',
      openJobCount: 0,
      lastSuccessAt: null,
      trackingStartedAt: null,
    };
    fetchMock.mockResolvedValue(jsonResponse({ companies: [DISCOVERING] }));
    renderWithProviders(<MyCompaniesList />);

    const row = await screen.findByTestId('my-company-row');
    expect(within(row).getByText('Setting up…')).toBeInTheDocument();
  });

  it('keeps polling while a board is still discovering (poll predicate)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const DISCOVERING: UserCompany = {
        id: 'u-discover02',
        displayName: 'careers.acme.example',
        ats: 'discovered',
        boardToken: 'https://careers.acme.example/jobs',
        sourceId: 'custom:u-discover02',
        healthState: 'discovering',
        openJobCount: 0,
        lastSuccessAt: null,
        trackingStartedAt: null,
      };
      fetchMock.mockResolvedValue(jsonResponse({ companies: [DISCOVERING] }));
      renderWithProviders(<MyCompaniesList />);

      await screen.findByTestId('my-company-row');
      const callsAfterLoad = fetchMock.mock.calls.length;

      // The 15s poll interval fires while a discovering row is present.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(16_000);
      });
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterLoad);
    } finally {
      vi.useRealTimers();
    }
  });

  it('stops polling once every row is settled (healthy with jobs)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const SETTLED: UserCompany = {
        id: 'u-settled001',
        displayName: 'Ramp',
        ats: 'ashby',
        boardToken: 'ramp',
        sourceId: 'custom:u-settled001',
        healthState: 'healthy',
        openJobCount: 42,
        lastSuccessAt: '2026-08-09T10:00:00Z',
        trackingStartedAt: '2026-08-01T00:00:00Z',
      };
      fetchMock.mockResolvedValue(jsonResponse({ companies: [SETTLED] }));
      renderWithProviders(<MyCompaniesList />);

      await screen.findByTestId('my-company-row');
      const callsAfterLoad = fetchMock.mock.calls.length;

      await act(async () => {
        await vi.advanceTimersByTimeAsync(16_000);
      });
      expect(fetchMock.mock.calls.length).toBe(callsAfterLoad);
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders a REFUSE state as a "Not trackable" badge (E7 Phase 3b)', async () => {
    // A discovery that refused surfaces in the list as a disabled, refused row.
    const REFUSED: UserCompany = {
      id: 'u-refused0001',
      displayName: 'careers.acme.example',
      ats: 'discovered',
      boardToken: 'https://careers.acme.example/jobs',
      sourceId: 'custom:u-refused0001',
      healthState: 'refused',
      openJobCount: 0,
      lastSuccessAt: null,
      trackingStartedAt: null,
    };
    fetchMock.mockResolvedValue(jsonResponse({ companies: [REFUSED] }));
    renderWithProviders(<MyCompaniesList />);

    const row = await screen.findByTestId('my-company-row');
    expect(within(row).getByText('Not trackable')).toBeInTheDocument();
  });
});

// ── the discovery-progress checklist, and its flag ─────────────────────────
//
// The flag gate lives in `MyCompaniesList` (not in the checklist component), so this
// is where "flag OFF renders exactly what shipped before" has to be pinned. Both
// halves render the SAME payload — a discovering row carrying a real checklist — so
// the only difference under test is the flag.

const DISCOVERING_WITH_CHECKLIST: UserCompany = {
  id: 'u-discover03',
  displayName: 'Acme',
  ats: 'discovered',
  boardToken: 'https://careers.acme.example/jobs',
  sourceId: 'custom:u-discover03',
  healthState: 'discovering',
  openJobCount: 0,
  lastSuccessAt: null,
  trackingStartedAt: null,
  discovery: {
    steps: [
      {
        key: 'open_page',
        status: 'done',
        result: 'opened careers.acme.example — recorded 14 JSON request(s)',
      },
      { key: 'find_feed', status: 'active', result: null },
      { key: 'verify_read', status: 'pending', result: null },
      { key: 'ready', status: 'pending', result: null },
    ],
    outcome: 'running',
    liveViewUrl: null,
    // Deliberately RELATIVE to now, not a fixed date: the fast cadence is bought by a
    // recent progress write, so a hard-coded timestamp would silently age into the
    // wedged-row case and stop testing what it says it tests.
    updatedAt: new Date().toISOString(),
  },
};

/** The same row after its worker died mid-run — nothing has written progress since. */
const WEDGED_DISCOVERING: UserCompany = {
  ...DISCOVERING_WITH_CHECKLIST,
  id: 'u-discover04',
  discovery: {
    ...DISCOVERING_WITH_CHECKLIST.discovery!,
    updatedAt: new Date(Date.now() - 60 * 60_000).toISOString(),
  },
};

/**
 * Renders the list with the discovery-progress flag in the given state.
 *
 * `resetModules()` + a dynamic import, matching `customCompaniesFlagGate.test.tsx`:
 * `CUSTOM_COMPANIES_CONFIG` reads `import.meta.env` once at module load, and the
 * component and `testUtils` must come from the SAME freshly-imported module graph or
 * the store is built from a different copy of the API slice than the component renders
 * against.
 */
async function renderListWithFlag(flagEnabled: boolean) {
  vi.resetModules();
  vi.stubEnv('VITE_DISCOVERY_PROGRESS_ENABLED', flagEnabled ? 'true' : '');
  const [{ MyCompaniesList: List }, { renderWithProviders: renderIt }] = await Promise.all([
    import('../../../components/my-companies/MyCompaniesList'),
    import('../../../test/testUtils'),
  ]);
  return renderIt(<List />);
}

describe('MyCompaniesList discovery checklist', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('renders the 4-step checklist on a discovering row when the flag is ON', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ companies: [DISCOVERING_WITH_CHECKLIST] }));
    await renderListWithFlag(true);

    const row = await screen.findByTestId('my-company-row');
    const checklist = within(row).getByTestId('discovery-checklist');
    expect(within(checklist).getByText('Opening the page')).toBeInTheDocument();
    expect(within(checklist).getByText('Reading jobs')).toBeInTheDocument();
    // The badge is still there — the checklist is additive, not a replacement.
    expect(within(row).getByText('Setting up…')).toBeInTheDocument();
  });

  it('FLAG OFF renders identically to today: badge only, no checklist', async () => {
    // The named regression gate for DECISION D5. The payload is identical to the
    // flag-ON case above, so anything the checklist adds would show up here.
    fetchMock.mockResolvedValue(jsonResponse({ companies: [DISCOVERING_WITH_CHECKLIST] }));
    const { container } = await renderListWithFlag(false);

    const row = await screen.findByTestId('my-company-row');
    expect(within(row).getByText('Setting up…')).toBeInTheDocument();
    expect(within(row).getByText(/0 open jobs/i)).toBeInTheDocument();
    expect(within(row).getByText(/not yet checked/i)).toBeInTheDocument();
    expect(screen.queryByTestId('discovery-checklist')).not.toBeInTheDocument();
    expect(screen.queryByTestId('discovery-next-actions')).not.toBeInTheDocument();
    expect(screen.queryByText('Opening the page')).not.toBeInTheDocument();
    expect(container.querySelectorAll('iframe')).toHaveLength(0);
  });

  it('polls faster than 15s while a discovery is mid-run (flag ON)', async () => {
    // Four steps of a few seconds each read as a spinner at the 15s list cadence.
    // Same query, same component — only the interval changes (DECISION D2).
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      // A fresh Response per call: a polled query reads the body more than once, and a
      // single shared Response would be consumed after the first poll.
      fetchMock.mockImplementation(async () =>
        jsonResponse({ companies: [DISCOVERING_WITH_CHECKLIST] })
      );
      await renderListWithFlag(true);
      await screen.findByTestId('my-company-row');
      const callsAfterLoad = fetchMock.mock.calls.length;

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterLoad);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps the 15s cadence with the flag OFF', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      // A fresh Response per call: a polled query reads the body more than once, and a
      // single shared Response would be consumed after the first poll.
      fetchMock.mockImplementation(async () =>
        jsonResponse({ companies: [DISCOVERING_WITH_CHECKLIST] })
      );
      await renderListWithFlag(false);
      await screen.findByTestId('my-company-row');
      const callsAfterLoad = fetchMock.mock.calls.length;

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(fetchMock.mock.calls.length).toBe(callsAfterLoad);

      // ...and the pre-existing 15s poll still fires.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(11_000);
      });
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterLoad);
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows a refusal with its failed step and alternatives (flag ON)', async () => {
    const refused: UserCompany = {
      ...DISCOVERING_WITH_CHECKLIST,
      healthState: 'refused',
      discovery: {
        ...DISCOVERING_WITH_CHECKLIST.discovery!,
        outcome: 'refused',
        steps: [
          { key: 'open_page', status: 'done', result: 'opened careers.acme.example' },
          { key: 'find_feed', status: 'done', result: 'found 3 candidate feed(s)' },
          {
            key: 'verify_read',
            status: 'failed',
            result: 'only 1 of the 12 job(s) the browser saw came back from the replay',
          },
          { key: 'ready', status: 'pending', result: null },
        ],
      },
    };
    fetchMock.mockResolvedValue(jsonResponse({ companies: [refused] }));
    await renderListWithFlag(true);

    const row = await screen.findByTestId('my-company-row');
    expect(within(row).getByTestId('discovery-headline')).toHaveTextContent(
      /we couldn't read acme's board/i
    );
    expect(within(row).getByTestId('discovery-next-actions')).toBeInTheDocument();
    // The badge and the Remove button — the row's existing affordances — survive.
    expect(within(row).getByText('Not trackable')).toBeInTheDocument();
    expect(within(row).getByTestId('my-company-remove')).toBeInTheDocument();
  });

  it('drops the success summary once the first harvest lands (flag ON)', async () => {
    const tracked: UserCompany = {
      ...DISCOVERING_WITH_CHECKLIST,
      healthState: 'unverified',
      openJobCount: 42,
      lastSuccessAt: '2026-08-20T11:00:00Z',
      discovery: { ...DISCOVERING_WITH_CHECKLIST.discovery!, outcome: 'tracking' },
    };
    fetchMock.mockResolvedValue(jsonResponse({ companies: [tracked] }));
    await renderListWithFlag(true);

    await screen.findByTestId('my-company-row');
    expect(screen.queryByTestId('discovery-checklist')).not.toBeInTheDocument();
  });

  it('drops the success summary on a harvested board that has zero open jobs', async () => {
    // A tracked board can genuinely have no roles today. Keying the receipt on the job
    // count resurrected it — a green "We can read Acme's board" over a "0 open jobs"
    // chip, linking to postings the harvest had just proved gone.
    const tracked: UserCompany = {
      ...DISCOVERING_WITH_CHECKLIST,
      healthState: 'unverified',
      openJobCount: 0,
      lastSuccessAt: '2026-08-20T11:00:00Z',
      discovery: { ...DISCOVERING_WITH_CHECKLIST.discovery!, outcome: 'tracking' },
    };
    fetchMock.mockResolvedValue(jsonResponse({ companies: [tracked] }));
    await renderListWithFlag(true);

    const row = await screen.findByTestId('my-company-row');
    expect(within(row).getByText(/0 open jobs/i)).toBeInTheDocument();
    expect(screen.queryByTestId('discovery-checklist')).not.toBeInTheDocument();
  });

  it('drops back to the 15s cadence once a discovering row goes stale (flag ON)', async () => {
    // A row only leaves `discovering` when the task persists an outcome, and that task
    // is retry=1 — a flag flipped off mid-flight, an undrained queue or the documented
    // SIGKILL wedge all strand it there. Unbounded, the fast cadence would then hammer
    // the list endpoint every 4s for as long as the tab stays open.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      fetchMock.mockImplementation(async () =>
        jsonResponse({ companies: [WEDGED_DISCOVERING] })
      );
      await renderListWithFlag(true);
      await screen.findByTestId('my-company-row');
      const callsAfterLoad = fetchMock.mock.calls.length;

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(fetchMock.mock.calls.length).toBe(callsAfterLoad);

      // ...but the row is still settling, so the ordinary 15s poll keeps it alive.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(11_000);
      });
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterLoad);
    } finally {
      vi.useRealTimers();
    }
  });

  it('survives a failed poll: keeps the rows, keeps polling (flag ON)', async () => {
    // RTK Query keeps `data` from the last good fetch and still marks the entry
    // rejected. Blanking the list on that deleted every row AND unmounted the poller,
    // so one transient 502 stopped auto-refresh for good — on a screen whose whole
    // point is being live.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let calls = 0;
      fetchMock.mockImplementation(async () => {
        calls += 1;
        // First poll after the initial load fails; everything after it succeeds.
        if (calls === 2) return jsonResponse({ detail: 'bad gateway' }, 502);
        return jsonResponse({ companies: [DISCOVERING_WITH_CHECKLIST] });
      });
      await renderListWithFlag(true);
      await screen.findByTestId('my-company-row');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      // The row and its checklist survive, and the staleness is stated rather than hidden.
      expect(screen.getByTestId('my-company-row')).toBeInTheDocument();
      expect(screen.getByTestId('discovery-checklist')).toBeInTheDocument();
      expect(screen.getByTestId('my-companies-refresh-warning')).toBeInTheDocument();

      // The next tick recovers on its own — no Retry click needed.
      const afterFailure = fetchMock.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(fetchMock.mock.calls.length).toBeGreaterThan(afterFailure);
      await waitFor(() => {
        expect(screen.queryByTestId('my-companies-refresh-warning')).not.toBeInTheDocument();
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('still shows the error card when the very first load fails', async () => {
    // The other half: with nothing cached there is no list to preserve, so the
    // full-width error + Retry is still the right render.
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'bad gateway' }, 502));
    await renderListWithFlag(true);

    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByTestId('my-company-row')).not.toBeInTheDocument();
  });
});
