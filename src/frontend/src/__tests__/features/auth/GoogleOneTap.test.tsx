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
  setGoogleCredential: mockSetGoogleCredential,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

describe('GoogleOneTap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: false,
      isLoading: false,
      setGoogleCredential: mockSetGoogleCredential,
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
      expect.objectContaining({ disabled: false })
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

  it('calls useGoogleOneTapLogin with disabled=true when loading', async () => {
    mockAuthState.isLoading = true;
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    expect(mockUseGoogleOneTapLogin).toHaveBeenCalledWith(
      expect.objectContaining({ disabled: true })
    );
  });

  it('onSuccess calls setGoogleCredential with the credential', async () => {
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    const config = mockUseGoogleOneTapLogin.mock.calls[0][0];
    config.onSuccess({ credential: 'google-jwt-token' });

    expect(mockSetGoogleCredential).toHaveBeenCalledWith('google-jwt-token');
  });

  it('onSuccess does not call setGoogleCredential when credential is missing', async () => {
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    const config = mockUseGoogleOneTapLogin.mock.calls[0][0];
    config.onSuccess({});

    expect(mockSetGoogleCredential).not.toHaveBeenCalled();
  });

  it('onError logs a warning and does not throw', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { GoogleOneTap } = await import('../../../features/auth/GoogleOneTap');
    render(<GoogleOneTap />);

    const config = mockUseGoogleOneTapLogin.mock.calls[0][0];
    expect(() => config.onError()).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith('Google One Tap failed');

    warnSpy.mockRestore();
  });
});
