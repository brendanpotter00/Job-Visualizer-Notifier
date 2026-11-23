// The browser's memory of accounts that have answered the first-sign-in
// questions, and the subject it is keyed by.
//
// Oracle for the subject: the backend's `get_normalized_subject`
// (src/backend/api/auth/jwt.py) — Auth0 `sub` unchanged, a Google-issued
// One-Tap `sub` prefixed `google|`, anything else unchanged. The memory only
// works if the browser spells the subject the way `User.providerSubject` does.
import { describe, it, expect, beforeEach } from 'vitest';
import {
  isRememberedAsAnswered,
  rememberAsAnswered,
  signInSubject,
} from '../../../components/onboarding/onboardingMemory';

function jwt(payload: Record<string, unknown>): string {
  const b64url = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `${b64url({ alg: 'RS256' })}.${b64url(payload)}.signature`;
}

describe('signInSubject', () => {
  it('uses the Auth0 sub as is (it already names its provider)', () => {
    expect(signInSubject('auth0|6b0464bc', null)).toBe('auth0|6b0464bc');
    expect(signInSubject('google-oauth2|123', jwt({ sub: '999', iss: 'accounts.google.com' }))).toBe(
      'google-oauth2|123'
    );
  });

  it('prefixes a Google-issued One-Tap sub with google|, for both issuer spellings', () => {
    expect(signInSubject(undefined, jwt({ sub: '1234567890', iss: 'https://accounts.google.com' }))).toBe(
      'google|1234567890'
    );
    expect(signInSubject(undefined, jwt({ sub: '42', iss: 'accounts.google.com' }))).toBe('google|42');
  });

  it('leaves a credential from any other issuer unprefixed (the e2e stack mints these)', () => {
    expect(signInSubject(undefined, jwt({ sub: 'e2e|onboarding-x', iss: 'https://e2e.local.test/' }))).toBe(
      'e2e|onboarding-x'
    );
  });

  it('is null when nothing readable identifies the reader', () => {
    expect(signInSubject(undefined, null)).toBeNull();
    expect(signInSubject(undefined, 'not-a-jwt')).toBeNull();
    expect(signInSubject(undefined, 'a.%%%.c')).toBeNull();
    expect(signInSubject(undefined, jwt({ iss: 'accounts.google.com' }))).toBeNull();
  });
});

describe('remembered accounts', () => {
  beforeEach(() => window.localStorage.clear());

  it('remembers an account once and recognises only that account', () => {
    expect(isRememberedAsAnswered('auth0|a')).toBe(false);
    rememberAsAnswered('auth0|a');
    rememberAsAnswered('auth0|a');
    expect(isRememberedAsAnswered('auth0|a')).toBe(true);
    expect(isRememberedAsAnswered('auth0|b')).toBe(false);
    expect(JSON.parse(window.localStorage.getItem('jvn.onboardingAnswered.v1') ?? '[]')).toEqual([
      'auth0|a',
    ]);
  });

  it('keeps the 20 most recent accounts', () => {
    for (let i = 0; i < 21; i += 1) rememberAsAnswered(`auth0|${i}`);
    expect(isRememberedAsAnswered('auth0|0')).toBe(false);
    expect(isRememberedAsAnswered('auth0|1')).toBe(true);
    expect(isRememberedAsAnswered('auth0|20')).toBe(true);
  });

  it('treats unreadable storage as "not remembered" (the reader is only held, never wrongly asked)', () => {
    window.localStorage.setItem('jvn.onboardingAnswered.v1', '{not json');
    expect(isRememberedAsAnswered('auth0|a')).toBe(false);
    window.localStorage.setItem('jvn.onboardingAnswered.v1', JSON.stringify({ 'auth0|a': true }));
    expect(isRememberedAsAnswered('auth0|a')).toBe(false);
    rememberAsAnswered('auth0|a');
    expect(isRememberedAsAnswered('auth0|a')).toBe(true);
  });

  it('ignores a storage that refuses writes', () => {
    const throwing = {
      getItem: () => null,
      setItem: () => {
        throw new Error('QuotaExceededError');
      },
    } as unknown as Storage;
    expect(() => rememberAsAnswered('auth0|a', throwing)).not.toThrow();
  });
});
