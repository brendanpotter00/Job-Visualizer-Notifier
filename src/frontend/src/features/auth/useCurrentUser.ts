import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from './useAuth';
import { fetchCurrentUser, type User } from './authService';

export function useCurrentUser() {
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
      setError(err instanceof Error ? err.message : 'Failed to load profile');
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [getToken]);

  useEffect(() => {
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
  }, [isAuthenticated, loadUser]);

  return { user, setUser, loading, error, reload: loadUser };
}
