import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { DiscoveryCTA } from '../../../components/my-companies/DiscoveryCTA';
import {
  isDiscoveryPending,
  type AddUserCompanyResult,
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

const URL = 'https://acme.example/careers';
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('isDiscoveryPending', () => {
  it('discriminates the 202 discovery_pending body from a tracked UserCompany', () => {
    const pending: AddUserCompanyResult = {
      status: 'discovery_pending',
      detail: 'One-time setup — jobs appear after the first scan.',
    };
    const tracked: AddUserCompanyResult = {
      id: 'u-x',
      displayName: 'Acme',
      ats: 'discovered',
      boardToken: 'acme',
      sourceId: 'custom:u-x',
      healthState: 'unverified',
      openJobCount: 0,
      lastSuccessAt: null,
      trackingStartedAt: null,
    };
    expect(isDiscoveryPending(pending)).toBe(true);
    expect(isDiscoveryPending(tracked)).toBe(false);
  });
});

describe('DiscoveryCTA', () => {
  it('offers the one-time discovery button before submit', () => {
    renderWithProviders(<DiscoveryCTA url={URL} />);
    expect(screen.getByTestId('discovery-button')).toBeInTheDocument();
    expect(screen.getByTestId('discovery-button')).toHaveTextContent('Try one-time discovery');
  });

  it('shows the one-time-setup pending state on a 202 discovery_pending', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          status: 'discovery_pending',
          detail:
            "One-time setup — we're figuring out how to read this board; jobs appear after the first scan.",
          finalUrl: URL,
        },
        202,
      ),
    );
    renderWithProviders(<DiscoveryCTA url={URL} />);
    await userEvent.click(screen.getByTestId('discovery-button'));

    await waitFor(() =>
      expect(screen.getByTestId('discovery-pending')).toBeInTheDocument(),
    );
    expect(screen.getByText('One-time setup')).toBeInTheDocument();
    expect(screen.getByText(/jobs appear after the first scan/)).toBeInTheDocument();
    // The pre-submit prompt/button is gone once discovery is pending.
    expect(screen.queryByTestId('discovery-button')).not.toBeInTheDocument();
  });

  it('surfaces an error state when discovery cannot be started', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'nope' }, 503));
    renderWithProviders(<DiscoveryCTA url={URL} />);
    await userEvent.click(screen.getByTestId('discovery-button'));

    await waitFor(() =>
      expect(screen.getByTestId('discovery-error')).toBeInTheDocument(),
    );
  });
});
