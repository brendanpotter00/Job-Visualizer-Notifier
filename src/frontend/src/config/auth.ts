export interface AuthConfig {
  domain: string;
  clientId: string;
  redirectUri: string;
  audience: string;
  googleClientId: string;
  isEnabled: boolean;
}

// Guarded so module evaluation doesn't crash in non-DOM contexts
// (SSR, Node-only tests that don't pull in jsdom).
const defaultRedirectUri = typeof window !== 'undefined' ? window.location.origin : '';

export const AUTH_CONFIG: AuthConfig = {
  domain: import.meta.env.VITE_AUTH0_DOMAIN ?? '',
  clientId: import.meta.env.VITE_AUTH0_CLIENT_ID ?? '',
  redirectUri: import.meta.env.VITE_AUTH0_REDIRECT_URI || defaultRedirectUri,
  audience: import.meta.env.VITE_AUTH0_AUDIENCE ?? '',
  googleClientId: import.meta.env.VITE_GOOGLE_CLIENT_ID ?? '',
  isEnabled: !!(import.meta.env.VITE_AUTH0_DOMAIN && import.meta.env.VITE_AUTH0_CLIENT_ID),
};
