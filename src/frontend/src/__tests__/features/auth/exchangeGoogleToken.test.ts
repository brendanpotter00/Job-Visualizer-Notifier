import { describe, it, expect, vi, beforeEach } from 'vitest';
import { exchangeGoogleToken } from '../../../features/auth/exchangeGoogleToken';
import type { AuthConfig } from '../../../config/auth';

const baseConfig: AuthConfig = {
  domain: 'test.auth0.com',
  clientId: 'auth0-client',
  redirectUri: 'http://localhost:3000',
  audience: 'test-audience',
  googleClientId: 'test-google-client-id',
  isEnabled: true,
  bypassEnabled: false,
};

describe('exchangeGoogleToken', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('returns access_token on 200 success', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'auth0-jwt',
          id_token: 'unused',
          expires_in: 86400,
          token_type: 'Bearer',
          scope: 'openid profile email',
        }),
        { status: 200 }
      )
    );

    const result = await exchangeGoogleToken('google-id-token', baseConfig);
    expect(result).toBe('auth0-jwt');
  });

  it('POSTs to the correct Auth0 /oauth/token URL', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ access_token: 'auth0-jwt' }), { status: 200 })
    );

    await exchangeGoogleToken('google-id-token', baseConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      'https://test.auth0.com/oauth/token',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('sends Content-Type: application/x-www-form-urlencoded', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ access_token: 'auth0-jwt' }), { status: 200 })
    );

    await exchangeGoogleToken('google-id-token', baseConfig);

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/x-www-form-urlencoded',
        }),
      })
    );
  });

  it('sends the exact form-encoded body required by Auth0 token-exchange grant', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ access_token: 'auth0-jwt' }), { status: 200 })
    );

    await exchangeGoogleToken('google-id-token', baseConfig);

    const body = fetchSpy.mock.calls[0][1]!.body as URLSearchParams;
    const params = new URLSearchParams(body.toString());

    expect(params.get('grant_type')).toBe(
      'urn:ietf:params:oauth:grant-type:token-exchange'
    );
    expect(params.get('subject_token_type')).toBe(
      'http://auth0.com/oauth/token-type/google-id-token'
    );
    expect(params.get('subject_token')).toBe('google-id-token');
    expect(params.get('audience')).toBe('test-audience');
    expect(params.get('scope')).toBe('openid profile email');
    expect(params.get('client_id')).toBe('auth0-client');
    expect(params.has('client_secret')).toBe(false);
  });

  it('throws when Auth0 returns 4xx with error_description', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          error: 'invalid_grant',
          error_description: 'Invalid token',
        }),
        { status: 403 }
      )
    );

    await expect(exchangeGoogleToken('google-id-token', baseConfig)).rejects.toThrow(
      /403.*Invalid token|Invalid token.*403/
    );
  });

  it('throws when Auth0 returns 4xx with no JSON body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('not json at all', { status: 401 })
    );

    await expect(exchangeGoogleToken('google-id-token', baseConfig)).rejects.toThrow(
      /401/
    );
  });

  it('throws when Auth0 returns 200 but no access_token', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id_token: 'whatever' }), { status: 200 })
    );

    await expect(exchangeGoogleToken('google-id-token', baseConfig)).rejects.toThrow(
      /missing access_token/
    );
  });

  it('throws when Auth0 returns 200 with non-JSON body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('not json', { status: 200 })
    );

    await expect(exchangeGoogleToken('google-id-token', baseConfig)).rejects.toThrow(
      /200.*not valid JSON/
    );
  });

  it('throws when Auth0 returns 4xx with only error field (no error_description)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'invalid_request' }), { status: 400 })
    );

    await expect(exchangeGoogleToken('google-id-token', baseConfig)).rejects.toThrow(
      /400.*invalid_request|invalid_request.*400/
    );
  });

  it('throws when Auth0 returns 4xx with empty JSON body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({}), { status: 401 })
    );

    await expect(exchangeGoogleToken('google-id-token', baseConfig)).rejects.toThrow(
      /401.*\(no body\)|\(no body\).*401/
    );
  });

  it('throws when fetch itself rejects (network error)', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('boom'));

    await expect(exchangeGoogleToken('google-id-token', baseConfig)).rejects.toThrow(
      /boom/
    );
  });

  it('throws when config.domain is missing, without calling fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    await expect(
      exchangeGoogleToken('google-id-token', { ...baseConfig, domain: '' })
    ).rejects.toThrow(/Missing Auth0 config/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('throws when config.clientId is missing, without calling fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    await expect(
      exchangeGoogleToken('google-id-token', { ...baseConfig, clientId: '' })
    ).rejects.toThrow(/Missing Auth0 config/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('throws when config.audience is missing, without calling fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    await expect(
      exchangeGoogleToken('google-id-token', { ...baseConfig, audience: '' })
    ).rejects.toThrow(/Missing Auth0 config/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('throws when googleIdToken is empty, without calling fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    await expect(exchangeGoogleToken('', baseConfig)).rejects.toThrow(
      /Missing Google ID token/
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
