import type { AppState } from '@auth0/auth0-react';

/** A same-origin path ("/pricing?x=1"), or null: never a URL, "//host" or a backslash trick. */
export function safeReturnTo(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return null;
  return value;
}

// Auth0's callback always lands on "/"; HomeRoute navigates on to this.
let pending: string | null = null;

/** Auth0Provider's onRedirectCallback: strip `?code=&state=`, remember the returnTo. */
export function handleAuthRedirect(appState?: AppState): void {
  pending = safeReturnTo(appState?.returnTo);
  window.history.replaceState({}, document.title, window.location.pathname);
}

export function pendingReturnTo(): string | null {
  return pending;
}

export function clearPendingReturnTo(): void {
  pending = null;
}
