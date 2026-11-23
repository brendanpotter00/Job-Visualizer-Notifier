import type { ReactNode } from 'react';
import { CurrentUserContext } from './currentUserContext';
import { useCurrentUserState } from './useCurrentUser';

/**
 * Owns the page load's single `GET /api/users` and hands the result to every
 * `useCurrentUser()` below it. Mounted by `AuthProviders`, inside the auth
 * providers it reads the token from. See `useCurrentUser` for why one.
 */
export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const state = useCurrentUserState(true);
  return <CurrentUserContext.Provider value={state}>{children}</CurrentUserContext.Provider>;
}
