import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PricingPage } from '../../../pages/PricingPage/PricingPage';
import { renderWithProviders } from '../../../test/testUtils';
import { registerTokenGetter } from '../../../features/features/getTokenOrNull';
import type { SubscriptionStatus } from '../../../features/billing/billingApi';

// Node's built-in `Request` (undici) requires absolute URLs, and RTK Query's
// `fetchBaseQuery` builds `new Request('/api/billing/...')`. Resolve relative
// URLs against a dummy origin, as the feature/feedback API tests do.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const resolved =
      typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input;
    super(resolved, init);
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

const mockLoginWithReturnTo = vi.fn().mockResolvedValue(undefined);
let mockAuth = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  user: undefined,
  login: vi.fn(),
  loginWithReturnTo: mockLoginWithReturnTo,
  signup: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
};
vi.mock('../../../features/auth/useAuth', () => ({ useAuth: () => mockAuth }));

const mockGoToStripe = vi.fn();
vi.mock('../../../features/billing/billingApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../features/billing/billingApi')>();
  return { ...actual, goToStripe: (url: string) => mockGoToStripe(url) };
});

const FREE: SubscriptionStatus = {
  plan: 'free',
  status: null,
  isPro: false,
  hasSubscription: false,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  pastDueSince: null,
  graceEndsAt: null,
  billingEnabled: true,
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function routeFetch(handlers: Record<string, () => Response>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    const key = Object.keys(handlers).find((k) => url.endsWith(k));
    if (!key) throw new Error(`unexpected fetch ${url}`);
    return handlers[key]();
  });
}

function proCard() {
  return screen.getByRole('region', { name: 'Pro' });
}

describe('PricingPage', () => {
  beforeEach(() => {
    mockAuth = { ...mockAuth, isAuthenticated: false, isLoading: false, isEnabled: true };
    registerTokenGetter(async () => 'tok');
  });
  afterEach(() => {
    vi.clearAllMocks();
    registerTokenGetter(null);
  });

  it('shows Free as ruled rows and Pro as one large line, with no FAQ', () => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing'] });
    expect(screen.getByRole('heading', { level: 1, name: 'Pricing' })).toBeInTheDocument();
    // No eyebrow and no tagline (owner, 2026-11-15): "Pricing" appears once, as the h1.
    expect(
      screen.getAllByText('Pricing', { exact: true }).filter((el) => el.tagName !== 'A')
    ).toHaveLength(1);
    const free = screen.getByRole('region', { name: 'Free' });
    expect(
      within(free)
        .getAllByRole('listitem')
        .map((li) => li.textContent)
    ).toEqual([
      'Unlimited job access',
      'Curated companies',
      'Saved filters',
      'Hiring trends',
      'Limited MCP access',
    ]);
    expect(within(proCard()).getByText('Everything in Free, plus')).toBeInTheDocument();
    expect(within(proCard()).getByText('Unlimited MCP access')).toBeInTheDocument();
    expect(within(proCard()).queryByRole('listitem')).toBeNull();
    expect(screen.queryByText(/cancel any time/i)).toBeNull();
    expect(screen.queryByText(/billed monthly/i)).toBeNull();
    // Signed out: no billing request at all.
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('signed out: "Sign in to upgrade" returns to /pricing to resume checkout', async () => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing'] });
    await userEvent.click(within(proCard()).getByRole('button', { name: 'Sign in to upgrade' }));
    expect(mockLoginWithReturnTo).toHaveBeenCalledWith('/pricing?intent=pro');
  });

  it('free user: Upgrade starts Checkout and sends the browser to Stripe', async () => {
    mockAuth = { ...mockAuth, isAuthenticated: true };
    global.fetch = routeFetch({
      '/api/billing/subscription': () => json(200, FREE),
      '/api/billing/checkout-session': () =>
        json(200, { url: 'https://checkout.stripe.test/cs_1' }),
    }) as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing'] });
    const button = await within(proCard()).findByRole('button', { name: 'Upgrade to Pro' });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    await waitFor(() =>
      expect(mockGoToStripe).toHaveBeenCalledWith('https://checkout.stripe.test/cs_1')
    );
  });

  it('resumes Checkout once after sign-in (?intent=pro)', async () => {
    mockAuth = { ...mockAuth, isAuthenticated: true };
    const fetchMock = routeFetch({
      '/api/billing/subscription': () => json(200, FREE),
      '/api/billing/checkout-session': () =>
        json(200, { url: 'https://checkout.stripe.test/cs_2' }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing?intent=pro'] });
    await waitFor(() =>
      expect(mockGoToStripe).toHaveBeenCalledWith('https://checkout.stripe.test/cs_2')
    );
    const checkouts = fetchMock.mock.calls.filter(([input]) =>
      String(input instanceof Request ? input.url : input).endsWith('/checkout-session')
    );
    expect(checkouts).toHaveLength(1);
  });

  it('subscriber: the button is Manage billing (Customer Portal)', async () => {
    mockAuth = { ...mockAuth, isAuthenticated: true };
    global.fetch = routeFetch({
      '/api/billing/subscription': () =>
        json(200, { ...FREE, plan: 'pro', status: 'active', isPro: true, hasSubscription: true }),
      '/api/billing/portal-session': () => json(200, { url: 'https://billing.stripe.test/p' }),
    }) as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing'] });
    await userEvent.click(await within(proCard()).findByRole('button', { name: 'Manage billing' }));
    await waitFor(() =>
      expect(mockGoToStripe).toHaveBeenCalledWith('https://billing.stripe.test/p')
    );
  });

  it('billing not configured: Upgrade is disabled, with one line saying so', async () => {
    mockAuth = { ...mockAuth, isAuthenticated: true };
    global.fetch = routeFetch({
      '/api/billing/subscription': () => json(200, { ...FREE, billingEnabled: false }),
    }) as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing'] });
    expect(await within(proCard()).findByText('Checkout is not open yet.')).toBeInTheDocument();
    expect(within(proCard()).getByRole('button', { name: 'Upgrade to Pro' })).toBeDisabled();
  });

  it('shows the server reason when Checkout is refused', async () => {
    mockAuth = { ...mockAuth, isAuthenticated: true };
    global.fetch = routeFetch({
      '/api/billing/subscription': () => json(200, FREE),
      '/api/billing/checkout-session': () =>
        json(503, { detail: 'Billing is not configured on this server.' }),
    }) as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing'] });
    const button = await within(proCard()).findByRole('button', { name: 'Upgrade to Pro' });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Billing is not configured on this server.'
    );
    expect(mockGoToStripe).not.toHaveBeenCalled();
  });

  it.each([
    ['/pricing?reason=mcp_limit', 'You reached the free MCP limit. Pro removes it.'],
    ['/pricing?checkout=cancel', 'Checkout canceled. You were not charged.'],
  ])('%s shows one notice above the plans', (entry, text) => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: [entry] });
    expect(screen.getByRole('status')).toHaveTextContent(text);
  });

  it('a plain visit shows no notice', () => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing'] });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('after Checkout, says "Turning on Pro" until the webhook lands, then "You’re on Pro"', async () => {
    mockAuth = { ...mockAuth, isAuthenticated: true };
    let isPro = false;
    global.fetch = routeFetch({
      '/api/billing/subscription': () =>
        json(
          200,
          isPro
            ? { ...FREE, plan: 'pro', status: 'active', isPro: true, hasSubscription: true }
            : FREE
        ),
    }) as unknown as typeof fetch;
    renderWithProviders(<PricingPage />, { initialEntries: ['/pricing?checkout=success'] });
    expect(await screen.findByRole('status')).toHaveTextContent('Payment received. Turning on Pro');
    isPro = true;
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('You’re on Pro.'), {
      timeout: 4000,
    });
  });
});
