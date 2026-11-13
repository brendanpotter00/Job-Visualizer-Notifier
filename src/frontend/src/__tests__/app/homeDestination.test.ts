import { describe, it, expect } from 'vitest';
import {
  hasStoredAuthSession,
  jobsSearchFrom,
  resolveHomeDestination,
  type HomeDestinationInput,
} from '../../app/homeDestination';

/** Signed-out, auth settled, nothing in the URL or storage; each test overrides one axis. */
const ANON: HomeDestinationInput = {
  isAuthenticated: false,
  isLoading: false,
  bypassEnabled: false,
  search: '',
  hasStoredSession: false,
};

describe('resolveHomeDestination', () => {
  it('signed-out visitor → landing', () => {
    expect(resolveHomeDestination(ANON)).toBe('landing');
  });

  it('signed-in visitor → jobs', () => {
    expect(resolveHomeDestination({ ...ANON, isAuthenticated: true })).toBe('jobs');
  });

  // No spinner in front of the page that has to win a stranger over: with no
  // sign-in history the landing page renders while auth is still resolving.
  it('auth still loading, no sign-in history → landing at once', () => {
    expect(resolveHomeDestination({ ...ANON, isLoading: true })).toBe('landing');
  });

  it('auth still loading with a stored Auth0 session → wait (no landing-page flash)', () => {
    expect(resolveHomeDestination({ ...ANON, isLoading: true, hasStoredSession: true })).toBe(
      'wait'
    );
  });

  it('auth still loading mid-callback (?code&state) → wait', () => {
    expect(
      resolveHomeDestination({ ...ANON, isLoading: true, search: '?code=abc&state=xyz' })
    ).toBe('wait');
  });

  it('a stored session that resolves signed-out → landing', () => {
    expect(resolveHomeDestination({ ...ANON, hasStoredSession: true })).toBe('landing');
  });

  // The bypass user is fake and always signed in; redirecting it would make the
  // landing page unreachable on every QA/Preview build.
  it('auth bypass (QA/Preview) → landing even though "signed in"', () => {
    expect(resolveHomeDestination({ ...ANON, bypassEnabled: true, isAuthenticated: true })).toBe(
      'landing'
    );
  });

  it.each([['?time=24h'], ['?category=backend'], ['?level=mid'], ['?location=SF'], ['?tag=x']])(
    'an old shared Recent Jobs link (%s) → jobs, signed out or not',
    (search) => {
      expect(resolveHomeDestination({ ...ANON, search })).toBe('jobs');
      expect(resolveHomeDestination({ ...ANON, search, bypassEnabled: true })).toBe('jobs');
    }
  );

  it('the landing page’s own ?data= toggle stays on the landing page', () => {
    expect(resolveHomeDestination({ ...ANON, search: '?data=sparse' })).toBe('landing');
  });
});

describe('jobsSearchFrom', () => {
  it('drops Auth0 callback params and keeps everything else', () => {
    expect(jobsSearchFrom('?code=abc&state=xyz&category=backend')).toBe('?category=backend');
    expect(jobsSearchFrom('?error=access_denied&error_description=nope')).toBe('');
  });

  it('returns an empty string for an empty query', () => {
    expect(jobsSearchFrom('')).toBe('');
  });
});

describe('hasStoredAuthSession', () => {
  function storageWith(keys: string[]): Storage {
    const map = new Map(keys.map((key) => [key, 'x']));
    return {
      get length() {
        return map.size;
      },
      key: (i: number) => Array.from(map.keys())[i] ?? null,
      getItem: (k: string) => map.get(k) ?? null,
      setItem: () => {},
      removeItem: () => {},
      clear: () => {},
    };
  }

  it('true when an auth0-spa-js cache entry exists', () => {
    expect(
      hasStoredAuthSession(storageWith(['other', '@@auth0spajs@@::client::aud::openid']))
    ).toBe(true);
  });

  it('false with no auth0 entries, and without storage at all', () => {
    expect(hasStoredAuthSession(storageWith(['jvn.something']))).toBe(false);
    expect(hasStoredAuthSession(undefined)).toBe(false);
  });

  it('false (not a crash) when storage throws', () => {
    const throwing = {
      get length(): number {
        throw new Error('SecurityError');
      },
    } as unknown as Storage;
    expect(hasStoredAuthSession(throwing)).toBe(false);
  });
});
