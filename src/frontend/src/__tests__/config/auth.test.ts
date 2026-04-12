import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('AUTH_CONFIG', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('isEnabled is true when both domain and clientId are set', async () => {
    vi.stubEnv('VITE_AUTH0_DOMAIN', 'test.auth0.com');
    vi.stubEnv('VITE_AUTH0_CLIENT_ID', 'test-client-id');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.isEnabled).toBe(true);
    vi.unstubAllEnvs();
  });

  it('isEnabled is false when domain is missing', async () => {
    vi.stubEnv('VITE_AUTH0_DOMAIN', '');
    vi.stubEnv('VITE_AUTH0_CLIENT_ID', 'test-client-id');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.isEnabled).toBe(false);
    vi.unstubAllEnvs();
  });

  it('isEnabled is false when clientId is missing', async () => {
    vi.stubEnv('VITE_AUTH0_DOMAIN', 'test.auth0.com');
    vi.stubEnv('VITE_AUTH0_CLIENT_ID', '');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.isEnabled).toBe(false);
    vi.unstubAllEnvs();
  });

  it('isEnabled is false when both are missing', async () => {
    vi.stubEnv('VITE_AUTH0_DOMAIN', '');
    vi.stubEnv('VITE_AUTH0_CLIENT_ID', '');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.isEnabled).toBe(false);
    vi.unstubAllEnvs();
  });

  it('reads domain from env', async () => {
    vi.stubEnv('VITE_AUTH0_DOMAIN', 'my-tenant.auth0.com');
    vi.stubEnv('VITE_AUTH0_CLIENT_ID', 'abc');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.domain).toBe('my-tenant.auth0.com');
    vi.unstubAllEnvs();
  });

  it('reads googleClientId from env', async () => {
    vi.stubEnv('VITE_GOOGLE_CLIENT_ID', 'google-123');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.googleClientId).toBe('google-123');
    vi.unstubAllEnvs();
  });

  it('redirectUri defaults to window.location.origin', async () => {
    vi.stubEnv('VITE_AUTH0_REDIRECT_URI', '');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.redirectUri).toBe(window.location.origin);
    vi.unstubAllEnvs();
  });

  it('reads redirectUri from env when set', async () => {
    vi.stubEnv('VITE_AUTH0_REDIRECT_URI', 'http://localhost:3000');
    const { AUTH_CONFIG } = await import('../../config/auth');
    expect(AUTH_CONFIG.redirectUri).toBe('http://localhost:3000');
    vi.unstubAllEnvs();
  });
});
