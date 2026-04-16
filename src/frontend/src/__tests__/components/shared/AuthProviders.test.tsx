import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// Mock the auth config so we can flip isEnabled per test.
let mockAuthConfig = {
  domain: 'test.auth0.com',
  clientId: 'auth0-client',
  redirectUri: 'http://localhost:3000',
  audience: 'test-audience',
  googleClientId: 'test-google-client-id',
  isEnabled: true,
  bypassEnabled: false,
};

vi.mock('../../../config/auth', () => ({
  get AUTH_CONFIG() {
    return mockAuthConfig;
  },
}));

// Replace the real GoogleOAuthProvider / Auth0Provider with passthroughs so
// the test doesn't need real Google / Auth0 scripts in jsdom.
vi.mock('@react-oauth/google', () => ({
  GoogleOAuthProvider: ({ children }: { children: ReactNode }) => (
    <div data-testid="google-oauth-provider">{children}</div>
  ),
}));

vi.mock('@auth0/auth0-react', () => ({
  Auth0Provider: ({ children }: { children: ReactNode }) => (
    <div data-testid="auth0-provider">{children}</div>
  ),
}));

vi.mock('../../../features/auth/GoogleCredentialContext', () => ({
  GoogleCredentialProvider: ({ children }: { children: ReactNode }) => (
    <div data-testid="google-credential-provider">{children}</div>
  ),
}));

// Sentinel so we can detect whether GoogleOneTap was rendered by AuthProviders.
vi.mock('../../../features/auth/GoogleOneTap', () => ({
  GoogleOneTap: () => <div data-testid="google-one-tap-rendered" />,
}));

describe('AuthProviders', () => {
  beforeEach(() => {
    mockAuthConfig = {
      domain: 'test.auth0.com',
      clientId: 'auth0-client',
      redirectUri: 'http://localhost:3000',
      audience: 'test-audience',
      googleClientId: 'test-google-client-id',
      isEnabled: true,
      bypassEnabled: false,
    };
  });

  it('does NOT render GoogleOneTap when auth is disabled', async () => {
    mockAuthConfig.isEnabled = false;
    const { AuthProviders } = await import('../../../components/shared/AuthProviders');

    render(
      <AuthProviders>
        <div>child</div>
      </AuthProviders>
    );

    // Key invariant: GoogleOneTap must NOT mount outside its GoogleOAuthProvider.
    expect(screen.queryByTestId('google-one-tap-rendered')).not.toBeInTheDocument();
    expect(screen.queryByTestId('google-oauth-provider')).not.toBeInTheDocument();
    expect(screen.getByText('child')).toBeInTheDocument();
  });

  it('short-circuits above real providers in bypass mode (no GoogleOneTap, no Auth0)', async () => {
    mockAuthConfig.bypassEnabled = true;
    // isEnabled could be either value in bypass — bypass takes precedence.
    mockAuthConfig.isEnabled = true;
    const { AuthProviders } = await import('../../../components/shared/AuthProviders');

    render(
      <AuthProviders>
        <div>child</div>
      </AuthProviders>
    );

    // In bypass mode, real providers must NOT mount — preview URLs can't
    // complete OAuth and empty clientIds would throw.
    expect(screen.queryByTestId('google-oauth-provider')).not.toBeInTheDocument();
    expect(screen.queryByTestId('auth0-provider')).not.toBeInTheDocument();
    expect(screen.queryByTestId('google-one-tap-rendered')).not.toBeInTheDocument();
    expect(screen.getByText('child')).toBeInTheDocument();
  });

  it('renders GoogleOneTap inside the providers when auth is enabled', async () => {
    const { AuthProviders } = await import('../../../components/shared/AuthProviders');

    render(
      <AuthProviders>
        <div>child</div>
      </AuthProviders>
    );

    const oneTap = screen.getByTestId('google-one-tap-rendered');
    expect(oneTap).toBeInTheDocument();
    // GoogleOneTap must be nested inside GoogleOAuthProvider so useGoogleOneTapLogin has context.
    expect(screen.getByTestId('google-oauth-provider')).toContainElement(oneTap);
    expect(screen.getByText('child')).toBeInTheDocument();
  });
});
