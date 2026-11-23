// One page load = ONE `GET /api/users`, shared by every caller.
//
// Regression for 2026-11-23: the user menu, the side menu, the PostHog
// identify hook and the onboarding gate each kept their own copy, so a page
// load sent four identical `GET /api/users`. Chrome runs identical concurrent
// GETs one after another, so the gate's copy — the one that decides whether
// the first-sign-in questions open — came back after three full round trips.
//
// Oracle: the number of requests the browser would send (the fetch mock), and
// what each caller renders. The wrong behaviour this rejects: one request per
// caller, and callers disagreeing after one of them updates the row.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { CurrentUserProvider } from '../../../features/auth/CurrentUserProvider';
import { useCurrentUser } from '../../../features/auth/useCurrentUser';

// Module-stable, like the real `getToken` (a new function each render would
// refetch on every render, which is a different bug).
const { TOKEN_GETTER } = vi.hoisted(() => ({ TOKEN_GETTER: async () => 'token' }));

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    user: { sub: 'auth0|shared' },
    login: vi.fn(),
    logout: vi.fn(),
    getToken: TOKEN_GETTER,
  }),
}));

const ROW = {
  id: 'u-shared',
  providerSubject: 'auth0|shared',
  email: 'shared@example.com',
  displayName: 'Before',
  givenName: null,
  familyName: null,
  pictureUrl: null,
  createdAt: '2026-11-23T10:00:00Z',
  updatedAt: '2026-11-23T10:00:00Z',
  isAdmin: false,
  onboardingCompletedAt: null,
};

function Reader({ name }: { name: string }) {
  const { user, loading } = useCurrentUser();
  return (
    <p data-testid={name}>
      {loading ? 'loading' : (user?.displayName ?? 'none')}
    </p>
  );
}

function Renamer() {
  const { setUser } = useCurrentUser();
  return (
    <button onClick={() => setUser((u) => (u ? { ...u, displayName: 'After' } : u))}>
      rename
    </button>
  );
}

const usersGets = (spy: ReturnType<typeof vi.spyOn>) =>
  spy.mock.calls.filter(([url]) => url === '/api/users').length;

describe('useCurrentUser under CurrentUserProvider', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => new Response(JSON.stringify(ROW), { status: 200 }));
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it('sends ONE GET /api/users for four callers, and all four see the row', async () => {
    render(
      <CurrentUserProvider>
        <Reader name="menu" />
        <Reader name="drawer" />
        <Reader name="analytics" />
        <Reader name="gate" />
      </CurrentUserProvider>
    );

    for (const name of ['menu', 'drawer', 'analytics', 'gate']) {
      expect(await screen.findByText('Before', { selector: `[data-testid="${name}"]` })).toBeInTheDocument();
    }
    expect(usersGets(fetchSpy)).toBe(1);
  });

  it("one caller's update reaches every other caller (one shared row, not copies)", async () => {
    render(
      <CurrentUserProvider>
        <Reader name="menu" />
        <Reader name="gate" />
        <Renamer />
      </CurrentUserProvider>
    );
    await screen.findByText('Before', { selector: '[data-testid="gate"]' });

    await act(async () => {
      screen.getByRole('button', { name: 'rename' }).click();
    });

    expect(screen.getByTestId('menu')).toHaveTextContent('After');
    expect(screen.getByTestId('gate')).toHaveTextContent('After');
    expect(usersGets(fetchSpy)).toBe(1);
  });

  it('without a provider each caller still works on its own (a unit test rendering one component)', async () => {
    render(<Reader name="alone" />);
    expect(await screen.findByText('Before', { selector: '[data-testid="alone"]' })).toBeInTheDocument();
    expect(usersGets(fetchSpy)).toBe(1);
  });
});
