import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// Bypass mode is decided at module load from AUTH_CONFIG.bypassEnabled, so we
// mock the config to true BEFORE importing useAuth. `useAuth0` and
// `useGoogleCredential` must NOT be called in bypass mode (their providers
// aren't mounted on bypass builds), so we wire both mocks to throw if invoked.
vi.mock('../../../config/auth', () => ({
  AUTH_CONFIG: {
    domain: '',
    clientId: '',
    redirectUri: '',
    audience: '',
    googleClientId: '',
    isEnabled: false,
    bypassEnabled: true,
  },
}));

vi.mock('@auth0/auth0-react', () => ({
  useAuth0: () => {
    throw new Error('useAuth0 must not be called in bypass mode');
  },
}));

vi.mock('../../../features/auth/useGoogleCredential', () => ({
  useGoogleCredential: () => {
    throw new Error('useGoogleCredential must not be called in bypass mode');
  },
}));

describe('useAuth (bypass mode)', () => {
  it('returns a fake authenticated user without touching real providers', async () => {
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    expect(result.current.isEnabled).toBe(true);
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.user).toEqual(
      expect.objectContaining({
        sub: 'bypass|qa-dev-user',
        email: 'qa-dev@bypass.local',
      })
    );
  });

  it('getToken returns a non-validating placeholder token', async () => {
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    const token = await result.current.getToken();
    expect(token).toBe('bypass-frontend-only-token');
  });

  it('returns a referentially-stable getToken across re-renders', async () => {
    // Regression guard: bypass `getToken` must keep a stable identity across
    // renders. `useFeaturesAuthBridge` runs useLayoutEffect(..., [getToken]); a
    // fresh getToken each render re-fires it every render, repeatedly clearing
    // the token getter so auth-gated queries 401 and strand the page on
    // "Loading…" (the Preview/QA-build symptom). A new object literal per render
    // would fail this.
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result, rerender } = renderHook(() => useAuth());

    const firstGetToken = result.current.getToken;
    const firstResult = result.current;
    act(() => rerender());

    expect(result.current.getToken).toBe(firstGetToken);
    expect(result.current).toBe(firstResult);
  });

  it('login is a no-op and resolves', async () => {
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    await expect(result.current.login()).resolves.toBeUndefined();
  });

  it('logout does not throw', async () => {
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    expect(() => result.current.logout()).not.toThrow();
    expect(infoSpy).toHaveBeenCalledWith(
      '[useAuth] Logout ignored: bypass mode is active.'
    );
    infoSpy.mockRestore();
  });
});
