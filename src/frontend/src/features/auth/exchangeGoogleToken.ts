import type { AuthConfig } from '../../config/auth';

interface Auth0TokenExchangeSuccess {
  access_token: string;
  id_token?: string;
  scope?: string;
  expires_in?: number;
  token_type?: string;
}

interface Auth0TokenExchangeError {
  error?: string;
  error_description?: string;
}

/**
 * Exchanges a Google ID token (from One Tap) for an Auth0 access token via
 * Auth0's Native Social Login token-exchange grant. Public SPA flow — no
 * client_secret. Returns the Auth0 access_token string on success; throws
 * Error on every failure mode for the caller to log.
 *
 * See docs/implementations/auth0NativeSocialLogin/PLAN.md "Shared Contracts".
 */
export async function exchangeGoogleToken(
  googleIdToken: string,
  config: AuthConfig,
): Promise<string> {
  if (!config.domain || !config.clientId || !config.audience) {
    throw new Error(
      '[exchangeGoogleToken] Missing Auth0 config (domain/clientId/audience)'
    );
  }
  if (!googleIdToken) {
    throw new Error('[exchangeGoogleToken] Missing Google ID token');
  }

  const body = new URLSearchParams({
    grant_type: 'urn:ietf:params:oauth:grant-type:token-exchange',
    subject_token_type: 'http://auth0.com/oauth/token-type/google-id-token',
    subject_token: googleIdToken,
    audience: config.audience,
    scope: 'openid profile email',
    client_id: config.clientId,
  });

  let response: Response;
  try {
    response = await fetch(`https://${config.domain}/oauth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`[exchangeGoogleToken] Network error: ${msg}`);
  }

  if (!response.ok) {
    let parsed: Auth0TokenExchangeError = {};
    try {
      parsed = (await response.json()) as Auth0TokenExchangeError;
    } catch {
      // body wasn't JSON; fall through with empty parsed
    }
    const detail = parsed.error_description ?? parsed.error ?? '(no body)';
    throw new Error(
      `[exchangeGoogleToken] Auth0 returned ${response.status}: ${detail}`
    );
  }

  const json = (await response.json()) as Auth0TokenExchangeSuccess;
  if (!json.access_token || typeof json.access_token !== 'string') {
    throw new Error('[exchangeGoogleToken] Auth0 response missing access_token');
  }
  return json.access_token;
}
