import { createContext, useState, useMemo, useCallback, type ReactNode } from 'react';

export interface GoogleCredentialState {
  googleCredential: string | null;
  setGoogleCredential: (credential: string | null) => void;
}

const STORAGE_KEY = 'jvn.googleCredential.v1';

// eslint-disable-next-line react-refresh/only-export-components
export const GoogleCredentialContext = createContext<GoogleCredentialState>({
  googleCredential: null,
  setGoogleCredential: () => {},
});

/**
 * Reads a previously persisted Google ID token from localStorage and returns
 * it only if its `exp` claim is still in the future. Expired or malformed
 * tokens are cleared so the user starts cleanly unauthenticated and
 * `auto_select` on Google One Tap can silently re-issue a fresh credential.
 */
function readStoredCredential(): string | null {
  if (typeof window === 'undefined' || !window.localStorage) return null;
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const [, payloadSegment] = raw.split('.');
    if (!payloadSegment) throw new Error('malformed');
    // Base64url -> base64
    const base64 = payloadSegment.replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(base64)) as { exp?: number };
    if (typeof payload.exp !== 'number' || payload.exp * 1000 <= Date.now()) {
      throw new Error('expired');
    }
    return raw;
  } catch {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    return null;
  }
}

function writeStoredCredential(value: string | null): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    if (value) {
      window.localStorage.setItem(STORAGE_KEY, value);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // ignore storage failures (quota, private mode, etc.)
  }
}

export function GoogleCredentialProvider({ children }: { children: ReactNode }) {
  const [googleCredential, setGoogleCredentialState] = useState<string | null>(() =>
    readStoredCredential()
  );

  const setGoogleCredential = useCallback((credential: string | null) => {
    writeStoredCredential(credential);
    setGoogleCredentialState(credential);
  }, []);

  const value = useMemo(
    () => ({ googleCredential, setGoogleCredential }),
    [googleCredential, setGoogleCredential]
  );
  return (
    <GoogleCredentialContext.Provider value={value}>
      {children}
    </GoogleCredentialContext.Provider>
  );
}
