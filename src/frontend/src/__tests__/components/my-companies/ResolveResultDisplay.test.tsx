import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { ResolveResultDisplay } from '../../../components/my-companies/ResolveResultDisplay';
import type {
  ResolveUrlResponse,
  UserCompany,
} from '../../../features/userCompanies/userCompaniesApi';

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

const FINAL_URL = 'https://boards.greenhouse.io/duolingo';

const OK_RESULT: ResolveUrlResponse = {
  candidate: {
    ats: 'greenhouse',
    boardToken: 'duolingo',
    providerConfig: {},
    sourceUrl: FINAL_URL,
  },
  probe: { ok: true, jobCount: 65, error: null },
  via: 'direct',
  hops: [],
  finalUrl: FINAL_URL,
};

const ADDED: UserCompany = {
  id: 'u-abc1234567',
  displayName: 'duolingo',
  ats: 'greenhouse',
  boardToken: 'duolingo',
  sourceId: 'custom:u-abc1234567',
  healthState: 'unverified',
  openJobCount: 0,
  lastSuccessAt: null,
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResolveResultDisplay — Add company CTA', () => {
  it('shows the "Track this company" button on a readable board (probe.ok)', () => {
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);
    expect(screen.getByTestId('add-company-button')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /track this company/i })).toBeInTheDocument();
  });

  it('does NOT show the Add button when the board could not be read (probe.ok === false)', () => {
    renderWithProviders(
      <ResolveResultDisplay
        result={{
          ...OK_RESULT,
          probe: { ok: false, jobCount: 0, error: 'HTTP 404' },
        }}
      />
    );
    expect(screen.queryByTestId('add-company-button')).not.toBeInTheDocument();
  });

  it('POSTs the finalUrl and confirms with a link to the trend page on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse(ADDED, 201));
    const user = userEvent.setup();
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

    await user.click(screen.getByTestId('add-company-button'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const req = fetchMock.mock.calls[0][0] as Request;
    expect(req.method).toBe('POST');
    expect(req.url).toMatch(/\/api\/users\/companies$/);
    await expect(req.text()).resolves.toBe(JSON.stringify({ url: FINAL_URL }));

    // Success confirmation + a link onward to the private trend page.
    const success = await screen.findByTestId('add-company-success');
    expect(success).toHaveTextContent(/now tracking duolingo/i);
    const link = screen.getByTestId('view-company-link');
    expect(link).toHaveAttribute('href', '/my-companies/u-abc1234567');
  });

  it('renders the 422 reason instead of crashing', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { reason: 'empty', detail: 'That board has no open jobs.', finalUrl: FINAL_URL },
        422
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

    await user.click(screen.getByTestId('add-company-button'));

    const error = await screen.findByTestId('add-company-error');
    expect(error).toHaveTextContent(/no open jobs/i);
    expect(error).toHaveTextContent('empty');
    expect(screen.queryByTestId('add-company-success')).not.toBeInTheDocument();
  });

  it('treats an idempotent 200 (already added) as success, not a crash', async () => {
    fetchMock.mockResolvedValue(jsonResponse(ADDED, 200));
    const user = userEvent.setup();
    renderWithProviders(<ResolveResultDisplay result={OK_RESULT} />);

    await user.click(screen.getByTestId('add-company-button'));

    expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
  });
});
