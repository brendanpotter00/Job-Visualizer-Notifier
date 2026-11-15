import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { AccountPage } from '../../../pages/AccountPage/AccountPage';
import { createTestStore } from '../../../test/testUtils';
import { registerTokenGetter } from '../../../features/features/getTokenOrNull';

// Node's undici Request needs absolute URLs; RTK Query passes '/api/billing/...'.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(
      typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input,
      init
    );
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

const flag = vi.hoisted(() => ({ showAccountPlanCard: false }));
vi.mock('../../../config/billing', () => ({ BILLING_CONFIG: flag }));

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    login: vi.fn(),
    loginWithReturnTo: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn().mockResolvedValue('tok'),
    user: null,
  }),
}));

vi.mock('../../../features/auth/authService', () => ({
  fetchCurrentUser: vi.fn().mockResolvedValue({
    id: 'abc123',
    providerSubject: 'auth0|test',
    email: 'test@example.com',
    displayName: 'Test',
    givenName: 'Test',
    familyName: 'User',
    pictureUrl: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    isAdmin: false,
  }),
  updateCurrentUser: vi.fn(),
}));

function renderPage() {
  return render(
    <Provider store={createTestStore()}>
      <MemoryRouter>
        <AccountPage />
      </MemoryRouter>
    </Provider>
  );
}

const billingCalls = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.filter(([input]) =>
    String(input instanceof Request ? input.url : input).includes('/api/billing/')
  );

describe('AccountPage Plan card (VITE_ACCOUNT_PLAN_CARD_ENABLED)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    registerTokenGetter(async () => 'tok');
    fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            plan: 'free',
            status: null,
            isPro: false,
            hasSubscription: false,
            currentPeriodEnd: null,
            cancelAtPeriodEnd: false,
            pastDueSince: null,
            graceEndsAt: null,
            billingEnabled: true,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
    );
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    registerTokenGetter(null);
    vi.clearAllMocks();
  });

  it('flag off (the default): no Plan card and no billing request', async () => {
    flag.showAccountPlanCard = false;
    renderPage();
    expect(await screen.findByText('test@example.com')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Plan' })).toBeNull();
    expect(billingCalls(fetchMock)).toHaveLength(0);
  });

  it('flag on: the Plan card sits below the profile with Upgrade and Compare plans', async () => {
    flag.showAccountPlanCard = true;
    renderPage();
    const card = await screen.findByRole('region', { name: 'Plan' });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Upgrade to Pro · $6/mo' })).toBeInTheDocument()
    );
    expect(screen.getByRole('link', { name: 'Compare plans' })).toHaveAttribute('href', '/pricing');
    // Below the profile card: the email precedes the Plan card in the document.
    const email = screen.getByText('test@example.com');
    expect(email.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
