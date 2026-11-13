/**
 * What `/` shows — pure, so every branch is unit-testable without the router
 * or the auth providers.
 *
 * `/` is the landing page for signed-out visitors and a doorway to the jobs
 * board for signed-in ones (owner decision, 2026-11-12, when the landing page
 * took the root from Recent Jobs).
 */
import { FILTER_PARAMS } from '../features/filters/urlFilters';

/** `landing` renders the page, `jobs` redirects to the board, `wait` holds a spinner. */
export type HomeDestination = 'landing' | 'jobs' | 'wait';

/**
 * Query params Auth0 puts on the redirect back to `/` after a hosted login.
 * Their presence means a sign-in is being completed right now; they must never
 * be carried along to `/jobs`.
 */
const AUTH_CALLBACK_PARAMS = ['code', 'state', 'error', 'error_description'] as const;

/** auth0-spa-js prefixes every localStorage cache entry with this. */
const AUTH0_CACHE_KEY_PREFIX = '@@auth0spajs@@';

export interface HomeDestinationInput {
  isAuthenticated: boolean;
  isLoading: boolean;
  /** VITE_AUTH_BYPASS: a fake user on QA/Preview builds. */
  bypassEnabled: boolean;
  /** `location.search`, including the leading `?` (or empty). */
  search: string;
  /** This browser holds an Auth0 session from an earlier visit (see `hasStoredAuthSession`). */
  hasStoredSession: boolean;
}

export function resolveHomeDestination(input: HomeDestinationInput): HomeDestination {
  const params = new URLSearchParams(input.search);

  // A shared Recent Jobs link from before the move (`/?category=…`) is a link to
  // the board, whoever opens it — never a landing page that drops its filters.
  if (FILTER_PARAMS.some((name) => params.has(name))) return 'jobs';

  // The bypass user is fake and always "signed in"; redirecting it would make
  // the landing page unreachable on every QA/Preview build.
  if (input.bypassEnabled) return 'landing';

  if (input.isAuthenticated) return 'jobs';

  // Auth is still resolving. A visitor with no sign-in history sees the landing
  // page at once (no spinner in front of the page that has to win them over);
  // if they turn out to be signed in after all, the redirect still fires when
  // auth resolves. Someone who is mid-callback or has a stored session is
  // almost certainly bound for the board, so they get a spinner instead of a
  // flash of the landing page.
  if (input.isLoading) {
    const midCallback = params.has('code') && params.has('state');
    if (midCallback || input.hasStoredSession) return 'wait';
  }
  return 'landing';
}

/**
 * The query to carry to `/jobs`: everything except Auth0's callback params, so
 * a fresh sign-in lands on a clean board URL and a shared filter link keeps its
 * filters.
 */
export function jobsSearchFrom(search: string): string {
  const params = new URLSearchParams(search);
  for (const name of AUTH_CALLBACK_PARAMS) params.delete(name);
  const rest = params.toString();
  return rest ? `?${rest}` : '';
}

/**
 * Synchronous hint that this browser holds an Auth0 session: an auth0-spa-js
 * localStorage cache entry (the provider runs with `cacheLocation=
 * "localstorage"`). Only used to pick a spinner over a flash of the landing
 * page while Auth0 resolves — never as proof of a session. A Google One Tap
 * credential needs no hint: it is read synchronously at startup, so
 * `isAuthenticated` is already true on the first render.
 */
export function hasStoredAuthSession(
  storage: Storage | undefined = typeof window === 'undefined' ? undefined : window.localStorage
): boolean {
  if (!storage) return false;
  try {
    for (let i = 0; i < storage.length; i += 1) {
      if (storage.key(i)?.startsWith(AUTH0_CACHE_KEY_PREFIX)) return true;
    }
  } catch {
    // Storage can throw (privacy mode, blocked site data): no hint, not a crash.
  }
  return false;
}
