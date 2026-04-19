import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';

const mockUseGoogleOneTapLogin = vi.fn();

vi.mock('@react-oauth/google', () => ({
  useGoogleOneTapLogin: (config: unknown) => mockUseGoogleOneTapLogin(config),
}));

const mockSetGoogleCredential = vi.fn();
let mockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
};
let mockAuthConfig = {
  domain: 'test.auth0.com',
  clientId: 'auth0-client',
  redirectUri: 'http://localhost:3000',
  audience: 'test-audience',
  googleClientId: 'test-google-client-id',
  isEnabled: true,
};

vi.mock('../../../config/auth', () => ({
  get AUTH_CONFIG() {
    return mockAuthConfig;
  },
}));

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

vi.mock('../../../features/auth/useGoogleCredential', () => ({
  useGoogleCredential: () => ({
    googleCredential: null,
    setGoogleCredential: mockSetGoogleCredential,
  }),
}));

const mockExchangeGoogleToken = vi.fn();

vi.mock('../../../features/auth/exchangeGoogleToken', () => ({
  exchangeGoogleToken: (...args: unknown[]) => mockExchangeGoogleToken(...args),
}));

describe('GoogleOneTap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: false,
      isLoading: false,
    };
    mockAuthConfig = {
      domain: 'test.auth0.com',
      clientId: 'auth0-client',
      redirectUri: 'http://localhost:3000',
      audience: 'test-audience',
      googleClientId: 'test-google-client-id',
      isEnabled: true,
    };
  });

  it('renders nothing', async () => {
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    const { container } = render(<GoogleOneTap />);
    expect(container.innerHTML).toBe('');
  });

  it('calls useGoogleOneTapLogin with disabled=false when enabled and not authenticated', async () => {
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    expect(mockUseGoogleOneTapLogin).toHaveBeenCalledWith(
      expect.objectContaining({ disabled: false, auto_select: true })
    );
  });

  it('calls useGoogleOneTapLogin with disabled=true when isEnabled is false', async () => {
    mockAuthState.isEnabled = false;
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    expect(mockUseGoogleOneTapLogin).toHaveBeenCalledWith(
      expect.objectContaining({ disabled: true })
    );
  });

  it('calls useGoogleOneTapLogin with disabled=true when authenticated', async () => {
    mockAuthState.isAuthenticated = true;
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    expect(mockUseGoogleOneTapLogin).toHaveBeenCalledWith(
      expect.objectContaining({ disabled: true })
    );
  });

  it('calls useGoogleOneTapLogin with disabled=true when googleClientId is empty', async () => {
    mockAuthConfig.googleClientId = '';
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    expect(mockUseGoogleOneTapLogin).toHaveBeenCalledWith(
      expect.objectContaining({ disabled: true })
    );
  });

  it('calls useGoogleOneTapLogin with disabled=true when loading', async () => {
    mockAuthState.isLoading = true;
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    expect(mockUseGoogleOneTapLogin).toHaveBeenCalledWith(
      expect.objectContaining({ disabled: true })
    );
  });

  it('onSuccess exchanges the Google credential for an Auth0 access token and stores it', async () => {
    mockExchangeGoogleToken.mockResolvedValue('auth0-access-token');
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    const config = mockUseGoogleOneTapLogin.mock.calls[0][0];
    await config.onSuccess({ credential: 'google-jwt-token' });

    expect(mockExchangeGoogleToken).toHaveBeenCalledTimes(1);
    expect(mockExchangeGoogleToken).toHaveBeenCalledWith(
      'google-jwt-token',
      expect.objectContaining(mockAuthConfig)
    );
    expect(mockSetGoogleCredential).toHaveBeenCalledTimes(1);
    expect(mockSetGoogleCredential).toHaveBeenCalledWith('auth0-access-token');
  });

  it('onSuccess does not call setGoogleCredential when credential is missing', async () => {
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    const config = mockUseGoogleOneTapLogin.mock.calls[0][0];
    await config.onSuccess({});

    expect(mockSetGoogleCredential).not.toHaveBeenCalled();
    expect(mockExchangeGoogleToken).not.toHaveBeenCalled();
  });

  it('onSuccess logs a warning and does not store credential when exchange fails', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockExchangeGoogleToken.mockRejectedValue(
      new Error('Auth0 returned 403: Invalid token')
    );
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    const config = mockUseGoogleOneTapLogin.mock.calls[0][0];
    await config.onSuccess({ credential: 'google-jwt-token' });

    expect(mockSetGoogleCredential).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringMatching(/Auth0 token exchange failed/),
      expect.any(String)
    );

    warnSpy.mockRestore();
  });

  it('onError logs a warning and does not throw', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    const config = mockUseGoogleOneTapLogin.mock.calls[0][0];
    expect(() => config.onError()).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(
      '[GoogleOneTap] Login failed — user may have dismissed the prompt or cookies are blocked'
    );

    warnSpy.mockRestore();
  });
});
