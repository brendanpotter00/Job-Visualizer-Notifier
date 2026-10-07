export interface AuthConfig {
  domain: string;
  clientId: string;
  redirectUri: string;
  audience: string;
  googleClientId: string;
  isEnabled: boolean;
  // QA-only bypass. When VITE_AUTH_BYPASS === 'true' the frontend skips real
  // Auth0/Google providers and useAuth() returns a fake authenticated user, so
  // auth-gated UI is reachable on Preview deploys where real OAuth callbacks
  // (dynamic preview URLs, CORS, etc.) cannot complete. Backend calls with the
  // resulting token will still 401 — this is deliberately frontend-only so the
  // flag has no authn value if it ever leaks outside Preview.
  bypassEnabled: boolean;
  // LOCAL-ONLY admin bypass (VITE_DEV_AUTH_BYPASS=1 under `vite` dev). The
  // frontend treats the user as signed in WITHOUT a token and sends no
  // Authorization header; the local backend's DEV_AUTH_BYPASS_EMAIL then maps
  // the unauthenticated loopback request to that admin, and AdminRoute still
  // reads the real isAdmin from /api/users. Unlike `bypassEnabled` this grants
  // nothing on its own: without the backend half every admin call 401s.
  devAdminBypassEnabled: boolean;
}

// Guarded so module evaluation doesn't crash in non-DOM contexts
// (SSR, Node-only tests that don't pull in jsdom).
const defaultRedirectUri = typeof window !== 'undefined' ? window.location.origin : '';

const bypassEnabled = import.meta.env.VITE_AUTH_BYPASS === 'true';

// LOCAL-ONLY. Vite replaces import.meta.env.DEV with `false` in `vite build`, so this branch is dead code in production.
const devAdminBypassEnabled = import.meta.env.DEV && import.meta.env.VITE_DEV_AUTH_BYPASS === '1';

if (bypassEnabled && devAdminBypassEnabled) {
  // Two fake-auth modes at once would make useAuth's dispatch order decide
  // which one silently wins. Fail loud at startup instead.
  throw new Error(
    '[auth] VITE_AUTH_BYPASS and VITE_DEV_AUTH_BYPASS are both set. Unset one of them.'
  );
}

export const AUTH_CONFIG: AuthConfig = {
  domain: import.meta.env.VITE_AUTH0_DOMAIN ?? '',
  clientId: import.meta.env.VITE_AUTH0_CLIENT_ID ?? '',
  redirectUri: import.meta.env.VITE_AUTH0_REDIRECT_URI || defaultRedirectUri,
  audience: import.meta.env.VITE_AUTH0_AUDIENCE ?? '',
  googleClientId: import.meta.env.VITE_GOOGLE_CLIENT_ID ?? '',
  isEnabled: !!(import.meta.env.VITE_AUTH0_DOMAIN && import.meta.env.VITE_AUTH0_CLIENT_ID),
  bypassEnabled,
  devAdminBypassEnabled,
};

if (bypassEnabled) {
  console.warn(
    '[auth] VITE_AUTH_BYPASS is ON — using fake authenticated user. ' +
      'This should only happen on QA/Preview builds, never production.'
  );
}

if (devAdminBypassEnabled) {
  console.warn(
    '[auth] VITE_DEV_AUTH_BYPASS is ON (local dev only) — signed in as the local admin with NO token. ' +
      'Admin calls only work against a local backend started with DEV_AUTH_BYPASS_EMAIL.'
  );
}
