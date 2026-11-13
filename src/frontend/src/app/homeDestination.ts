import { FILTER_PARAMS } from '../features/filters/urlFilters';

export type HomeDestination = 'landing' | 'jobs' | 'wait';

const AUTH_CALLBACK_PARAMS = ['code', 'state', 'error', 'error_description'] as const;

const AUTH0_CACHE_KEY_PREFIX = '@@auth0spajs@@';

export interface HomeDestinationInput {
  isAuthenticated: boolean;
  isLoading: boolean;
  bypassEnabled: boolean;
  search: string;
  hasStoredSession: boolean;
}

export function resolveHomeDestination(input: HomeDestinationInput): HomeDestination {
  const params = new URLSearchParams(input.search);

  if (FILTER_PARAMS.some((name) => params.has(name))) return 'jobs';

  if (input.bypassEnabled) return 'landing';

  if (input.isAuthenticated) return 'jobs';

  if (input.isLoading) {
    const midCallback = params.has('code') && params.has('state');
    if (midCallback || input.hasStoredSession) return 'wait';
  }
  return 'landing';
}

export function jobsSearchFrom(search: string): string {
  const params = new URLSearchParams(search);
  for (const name of AUTH_CALLBACK_PARAMS) params.delete(name);
  const rest = params.toString();
  return rest ? `?${rest}` : '';
}

function defaultStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function hasStoredAuthSession(storage: Storage | undefined = defaultStorage()): boolean {
  if (!storage) return false;
  try {
    for (let i = 0; i < storage.length; i += 1) {
      if (storage.key(i)?.startsWith(AUTH0_CACHE_KEY_PREFIX)) return true;
    }
  } catch {
    return false;
  }
  return false;
}
