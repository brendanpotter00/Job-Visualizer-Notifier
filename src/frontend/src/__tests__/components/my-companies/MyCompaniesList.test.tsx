import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
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
    expect(within(rowA).getByText(/tracking — building history/i)).toBeInTheDocument();
    expect(within(rowA).getByText(/0 open jobs/i)).toBeInTheDocument();
    expect(within(rowA).getByText(/not yet checked/i)).toBeInTheDocument();
    // Links to the private trend page by runtime id.
    expect(within(rowA).getByTestId('my-company-link')).toHaveAttribute(
      'href',
      '/my-companies/u-aaaaaaaaaa'
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
});
