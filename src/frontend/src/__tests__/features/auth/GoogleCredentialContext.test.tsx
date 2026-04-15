import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import {
  GoogleCredentialProvider,
} from '../../../features/auth/GoogleCredentialContext';
import { useGoogleCredential } from '../../../features/auth/useGoogleCredential';

const STORAGE_KEY = 'jvn.googleCredential.v1';

/** Build a minimal (unsigned) JWT whose payload carries the given `exp`. */
function makeJwt(expSeconds: number): string {
  const header = btoa(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const payload = btoa(JSON.stringify({ exp: expSeconds }));
  return `${header}.${payload}.sig`;
}

function wrapper({ children }: { children: ReactNode }) {
  return <GoogleCredentialProvider>{children}</GoogleCredentialProvider>;
}

describe('GoogleCredentialProvider', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('hydrates from localStorage when a non-expired JWT is present', () => {
    const token = makeJwt(Math.floor(Date.now() / 1000) + 3600);
    window.localStorage.setItem(STORAGE_KEY, token);

    const { result } = renderHook(() => useGoogleCredential(), { wrapper });

    expect(result.current.googleCredential).toBe(token);
  });

  it('treats an expired JWT as absent and removes the stored key', () => {
    const token = makeJwt(Math.floor(Date.now() / 1000) - 10);
    window.localStorage.setItem(STORAGE_KEY, token);

    const { result } = renderHook(() => useGoogleCredential(), { wrapper });

    expect(result.current.googleCredential).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('ignores malformed stored values and clears them', () => {
    window.localStorage.setItem(STORAGE_KEY, 'not-a-jwt');

    const { result } = renderHook(() => useGoogleCredential(), { wrapper });

    expect(result.current.googleCredential).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('writes to localStorage when setGoogleCredential is called with a value', () => {
    const { result } = renderHook(() => useGoogleCredential(), { wrapper });
    const token = makeJwt(Math.floor(Date.now() / 1000) + 3600);

    act(() => {
      result.current.setGoogleCredential(token);
    });

    expect(result.current.googleCredential).toBe(token);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(token);
  });

  it('removes the localStorage key when setGoogleCredential is called with null', () => {
    const token = makeJwt(Math.floor(Date.now() / 1000) + 3600);
    window.localStorage.setItem(STORAGE_KEY, token);

    const { result } = renderHook(() => useGoogleCredential(), { wrapper });
    expect(result.current.googleCredential).toBe(token);

    act(() => {
      result.current.setGoogleCredential(null);
    });

    expect(result.current.googleCredential).toBeNull();
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('renders children', () => {
    const { getByText } = render(
      <GoogleCredentialProvider>
        <span>child</span>
      </GoogleCredentialProvider>
    );
    expect(getByText('child')).toBeTruthy();
  });
});
