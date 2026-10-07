import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

// Dev-admin-bypass mode is decided at module load from
// AUTH_CONFIG.devAdminBypassEnabled, so the config is mocked BEFORE useAuth is
// imported. useAuth0 / useGoogleCredential must never run in this mode (their
// providers are not mounted), so both mocks throw if invoked.
vi.mock('../../../config/auth', () => ({
  AUTH_CONFIG: {
    domain: '',
    clientId: '',
    redirectUri: '',
    audience: '',
    googleClientId: '',
    isEnabled: false,
    bypassEnabled: false,
    devAdminBypassEnabled: true,
  },
}));

vi.mock('@auth0/auth0-react', () => ({
  useAuth0: () => {
    throw new Error('useAuth0 must not be called in dev admin bypass mode');
  },
}));

vi.mock('../../../features/auth/useGoogleCredential', () => ({
  useGoogleCredential: () => {
    throw new Error('useGoogleCredential must not be called in dev admin bypass mode');
  },
}));

describe('useAuth (local dev admin bypass)', () => {
  afterEach(async () => {
    const { registerTokenGetter } = await import('../../../features/features/getTokenOrNull');
    registerTokenGetter(null);
    vi.restoreAllMocks();
  });

  it('is signed in without touching Auth0, as the placeholder local admin', async () => {
    const { useAuth, useAuthDevAdminBypass } = await import('../../../features/auth/useAuth');
    expect(useAuth).toBe(useAuthDevAdminBypass);

    const { result } = renderHook(() => useAuth());
    expect(result.current.isEnabled).toBe(true);
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.user).toEqual({
      sub: 'dev-bypass|local',
      name: 'Local admin (dev bypass)',
    });
  });

  it('has no token: getToken rejects with NotAuthenticatedError', async () => {
    const { useAuth, NotAuthenticatedError } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    await expect(result.current.getToken()).rejects.toBeInstanceOf(NotAuthenticatedError);
  });

  it('so getTokenOrNull gives null (no Authorization header) and logs no warning', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { registerTokenGetter, getTokenOrNull } =
      await import('../../../features/features/getTokenOrNull');
    const { result } = renderHook(() => useAuth());

    registerTokenGetter(result.current.getToken);
    await expect(getTokenOrNull()).resolves.toBeNull();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('keeps a referentially stable result across re-renders', async () => {
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result, rerender } = renderHook(() => useAuth());
    const first = result.current;
    act(() => rerender());
    expect(result.current).toBe(first);
    expect(result.current.getToken).toBe(first.getToken);
  });

  it('login and logout are no-ops', async () => {
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    await expect(result.current.login()).resolves.toBeUndefined();
    expect(() => result.current.logout()).not.toThrow();
    expect(result.current.isAuthenticated).toBe(true);
    infoSpy.mockRestore();
  });

  it('useCurrentUser asks /api/users with NO Authorization header and reads isAdmin from it', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 'u1',
          providerSubject: 'dev-bypass|admin@example.com',
          email: 'admin@example.com',
          displayName: null,
          givenName: null,
          familyName: null,
          pictureUrl: null,
          createdAt: '2026-10-07T00:00:00Z',
          updatedAt: '2026-10-07T00:00:00Z',
          isAdmin: true,
        }),
        { status: 200 }
      )
    );
    const { useCurrentUser } = await import('../../../features/auth/useCurrentUser');
    const { result } = renderHook(() => useCurrentUser());

    await waitFor(() => expect(result.current.user?.isAdmin).toBe(true));
    expect(result.current.error).toBeNull();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('/api/users');
    expect((init?.headers as Record<string, string>).Authorization).toBeUndefined();
    expect(init?.headers).toEqual({ Accept: 'application/json' });
  });
});
