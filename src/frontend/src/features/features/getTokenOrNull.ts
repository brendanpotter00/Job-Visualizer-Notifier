import { NotAuthenticatedError } from '../auth/useAuth';

type TokenGetter = () => Promise<string>;

let currentGetter: TokenGetter | null = null;

export function registerTokenGetter(getter: TokenGetter | null): void {
  currentGetter = getter;
}

export async function getTokenOrNull(): Promise<string | null> {
  if (!currentGetter) return null;
  try {
    const token = await currentGetter();
    return token ?? null;
  } catch (e) {
    // `useAuth().getToken()` throws `NotAuthenticatedError` on the normal
    // signed-out path (see `features/auth/useAuth.ts`). This is the EXPECTED
    // rejection reason for anonymous callers and must not produce a warn log,
    // or every anonymous page load would spam the console. Any other
    // rejection (real SDK failure — network errors, token refresh failures,
    // etc.) is logged so the symptom is debuggable
    // (see `feedback_correctness_over_dont_crash`).
    if (e instanceof NotAuthenticatedError) {
      return null;
    }
    console.warn('[getTokenOrNull] token getter rejected:', e);
    return null;
  }
}
