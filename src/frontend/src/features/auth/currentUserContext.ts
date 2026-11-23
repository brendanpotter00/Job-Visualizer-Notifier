import { createContext } from 'react';
import type { CurrentUserState } from './useCurrentUser';

/** The page load's one shared current-user state; `null` outside `CurrentUserProvider`. */
export const CurrentUserContext = createContext<CurrentUserState | null>(null);
