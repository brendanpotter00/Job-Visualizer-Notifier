import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';


const mockLoginWithRedirect = vi.fn();
const mockLogout = vi.fn();
const mockGetAccessTokenSilently = vi.fn();

vi.mock('@auth0/auth0-react', () => ({
  useAuth0: () => ({
    isAuthenticated: mockAuth0State.isAuthenticated,
    isLoading: mockAuth0State.isLoading,
    user: mockAuth0State.user,
    loginWithRedirect: mockLoginWithRedirect,
    logout: mockLogout,
    getAccessTokenSilently: mockGetAccessTokenSilently,
  }),
}));

vi.mock('../../../config/auth', () => ({
  AUTH_CONFIG: {
    get isEnabled() {
      return mockAuthConfig.isEnabled;
    },
    domain: 'test.auth0.com',
    clientId: 'test-client',
    redirectUri: 'http://localhost:3000',
    audience: 'https://api.test.com',
    googleClientId: 'google-123',
  },
}));

let mockGoogleCredential: string | null = null;
const mockSetGoogleCredential = vi.fn((val: string | null) => {
  mockGoogleCredential = val;
});

vi.mock('../../../features/auth/useGoogleCredential', () => ({
  useGoogleCredential: () => ({
    get googleCredential() {
      return mockGoogleCredential;
    },
    setGoogleCredential: mockSetGoogleCredential,
  }),
}));

let mockAuth0State = {
  isAuthenticated: false,
  isLoading: false,
  user: null as Record<string, unknown> | null,
};

let mockAuthConfig = {
  isEnabled: true,
};

describe('useAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth0State = { isAuthenticated: false, isLoading: false, user: null };
    mockAuthConfig = { isEnabled: true };
    mockGoogleCredential = null;
  });

  it('returns isEnabled from config', async () => {
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isEnabled).toBe(true);
  });

  it('returns isEnabled false when config is disabled', async () => {
    mockAuthConfig.isEnabled = false;
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isEnabled).toBe(false);
  });

  it('returns isAuthenticated false when not authenticated and no credential', async () => {
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('returns isAuthenticated true when Auth0 is authenticated', async () => {
    mockAuth0State.isAuthenticated = true;
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('returns isAuthenticated true when googleCredential is set', async () => {
    mockGoogleCredential = 'google-jwt-token';
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('is authenticated via Google credential while Auth0 is still loading', async () => {
    // Crux of the One Tap fix: a fresh Google credential flips isAuthenticated
    // true (un-skipping the saved-filters query and hydrating filters) even while
    // Auth0's silent-auth is still in flight. isAuthenticated and isLoading are
    // independent, so One Tap no longer has to wait out Auth0's ~30s timeout.
    mockGoogleCredential = 'google-jwt-token';
    mockAuth0State.isLoading = true;
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(true);
  });

  it('returns isAuthenticated false when config is disabled even if Auth0 is authenticated', async () => {
    mockAuth0State.isAuthenticated = true;
    mockAuthConfig.isEnabled = false;
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('returns isLoading true when Auth0 is loading and enabled', async () => {
    mockAuth0State.isLoading = true;
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isLoading).toBe(true);
  });

  it('returns isLoading false when config is disabled', async () => {
    mockAuth0State.isLoading = true;
    mockAuthConfig.isEnabled = false;
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.isLoading).toBe(false);
  });

  it('getToken returns Auth0 token when Auth0 is authenticated', async () => {
    mockAuth0State.isAuthenticated = true;
    mockGetAccessTokenSilently.mockResolvedValue('auth0-token');
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    const token = await result.current.getToken();
    expect(token).toBe('auth0-token');
    expect(mockGetAccessTokenSilently).toHaveBeenCalled();
  });

  it('getToken returns googleCredential when only Google is authenticated', async () => {
    mockGoogleCredential = 'google-jwt';
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    const token = await result.current.getToken();
    expect(token).toBe('google-jwt');
  });

  it('getToken prefers Auth0 over Google credential', async () => {
    mockAuth0State.isAuthenticated = true;
    mockGoogleCredential = 'google-jwt';
    mockGetAccessTokenSilently.mockResolvedValue('auth0-token');
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    const token = await result.current.getToken();
    expect(token).toBe('auth0-token');
  });

  it('getToken throws when not authenticated', async () => {
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    await expect(result.current.getToken()).rejects.toThrow('Not authenticated');
  });

  it('login calls loginWithRedirect', async () => {
    mockLoginWithRedirect.mockResolvedValue(undefined);
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    await act(async () => {
      await result.current.login();
    });
    expect(mockLoginWithRedirect).toHaveBeenCalled();
  });

  it('login rethrows redirect failures after logging', async () => {
    // Pop-up blockers, CSP, and Auth0 misconfig all surface via loginWithRedirect
    // rejection; callers need the error to render user-visible feedback instead
    // of silently succeeding.
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const redirectError = new Error('Network error');
    mockLoginWithRedirect.mockRejectedValue(redirectError);
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    await expect(
      act(async () => {
        await result.current.login();
      })
    ).rejects.toThrow('Network error');
    expect(consoleSpy).toHaveBeenCalledWith('[useAuth] Login redirect failed:', redirectError);
    consoleSpy.mockRestore();
  });

  it('getToken throws session expired for login_required Auth0 error', async () => {
    mockAuth0State.isAuthenticated = true;
    const auth0Error = Object.assign(new Error('login_required'), { error: 'login_required' });
    mockGetAccessTokenSilently.mockRejectedValue(auth0Error);
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    await expect(result.current.getToken()).rejects.toThrow('Your session has expired');
  });

  it('logout clears googleCredential and calls Auth0 logout', async () => {
    mockAuth0State.isAuthenticated = true;
    mockGoogleCredential = 'google-jwt';
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());

    act(() => {
      result.current.logout();
    });

    expect(mockSetGoogleCredential).toHaveBeenCalledWith(null);
    expect(mockLogout).toHaveBeenCalledWith({
      logoutParams: { returnTo: window.location.origin },
    });
  });

  it('returns Auth0 user object', async () => {
    const mockUser = { sub: 'auth0|123', email: 'test@test.com' };
    mockAuth0State.isAuthenticated = true;
    mockAuth0State.user = mockUser;
    const { useAuth } = await import('../../../features/auth/useAuth');
    const { result } = renderHook(() => useAuth());
    expect(result.current.user).toEqual(mockUser);
  });
});
