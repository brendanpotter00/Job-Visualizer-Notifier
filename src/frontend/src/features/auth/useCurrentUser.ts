import { useState, useEffect, useCallback, useContext, useMemo, useRef } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useAuth } from './useAuth';
import { fetchCurrentUser, type User } from './authService';
import { CurrentUserContext } from './currentUserContext';
import { extractErrorMessage } from '../../lib/errors';

export interface CurrentUserState {
  user: User | null;
  setUser: Dispatch<SetStateAction<User | null>>;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

/**
 * The signed-in reader's `GET /api/users` row: ONE request and ONE state per
 * page load, shared by every caller through `CurrentUserProvider`.
 *
 * Shared on purpose. The user menu, the side menu, the PostHog identify hook
 * and the onboarding gate all read it, and when each kept its own copy a page
 * load sent four identical `GET /api/users`. Chrome's HTTP cache runs identical
 * concurrent GETs one after another (each waits for the previous response), so
 * the gate's copy — which decides whether the first-sign-in questions open —
 * came back only after three full round trips: about 4.5 s for a brand-new
 * account in production on 2026-11-23, while the Recent Jobs page loaded
 * underneath and the questions then snapped in over it.
 *
 * Outside a provider (a unit test rendering one component) it falls back to a
 * private copy that behaves exactly like the shared one. The app always mounts
 * the provider (`AuthProviders`).
 */
export function useCurrentUser(): CurrentUserState {
  const shared = useContext(CurrentUserContext);
  const own = useCurrentUserState(shared === null);
  return shared ?? own;
}

/** The fetch-and-hold state behind {@link useCurrentUser}. Inert when `enabled` is false. */
export function useCurrentUserState(enabled: boolean): CurrentUserState {
  const { isAuthenticated, getToken } = useAuth();

  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Tracks the in-flight fetch so callers of `reload` and the auth-state effect
  // can cancel a stale request — otherwise a fetch started while authenticated
  // could resolve after logout and repopulate `user` on a signed-out session.
  const activeController = useRef<AbortController | null>(null);

  const loadUser = useCallback(async () => {
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const fetchedUser = await fetchCurrentUser(token, controller.signal);
      if (!controller.signal.aborted) {
        setUser(fetchedUser);
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      // Log the raw error before we flatten it to a string — the stack /
      // abort / status detail is what ops needs to debug a /api/users
      // outage, and ``extractErrorMessage`` strips all of that. The
      // flattened string still goes to state for the UI.
      console.error('[useCurrentUser] fetch failed', err);
      setError(extractErrorMessage(err, 'Failed to load profile'));
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [getToken]);

  useEffect(() => {
    if (!enabled) return;
    if (isAuthenticated) {
      loadUser();
    } else {
      activeController.current?.abort();
      setUser(null);
      setError(null);
      setLoading(false);
    }
    return () => {
      activeController.current?.abort();
    };
  }, [enabled, isAuthenticated, loadUser]);

  return useMemo(
    () => ({ user, setUser, loading, error, reload: loadUser }),
    [user, loading, error, loadUser]
  );
}
