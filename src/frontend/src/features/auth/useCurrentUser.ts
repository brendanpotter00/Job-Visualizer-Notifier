import { useState, useEffect, useCallback } from 'react';
import { useAuth } from './useAuth';
import { fetchCurrentUser, type User } from './authService';

export function useCurrentUser() {
  const { isAuthenticated, getToken } = useAuth();

  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadUser = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const fetchedUser = await fetchCurrentUser(token);
      setUser(fetchedUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load profile');
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    if (isAuthenticated) {
      loadUser();
    } else {
      setUser(null);
      setError(null);
    }
  }, [isAuthenticated, loadUser]);

  return { user, setUser, loading, error, reload: loadUser };
}
