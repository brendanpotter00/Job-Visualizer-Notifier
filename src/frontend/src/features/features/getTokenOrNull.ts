type TokenGetter = () => Promise<string>;

let currentGetter: TokenGetter | null = null;

export function registerTokenGetter(getter: TokenGetter | null): void {
  currentGetter = getter;
}

/**
 * Sentinel message thrown by `useAuth().getToken()` on the normal signed-out
 * path (see `features/auth/useAuth.ts` — `throw new Error('Not authenticated')`
 * when neither Auth0 nor Google credential is present). This is the EXPECTED
 * rejection reason for anonymous callers and must not produce a warn log, or
 * every anonymous page load would spam the console. Real SDK failures
 * (network errors, token refresh failures, etc.) use different messages and
 * should still be surfaced.
 */
const NOT_AUTHENTICATED_SENTINEL = 'Not authenticated';

export async function getTokenOrNull(): Promise<string | null> {
  if (!currentGetter) return null;
  try {
    const token = await currentGetter();
    return token ?? null;
  } catch (e) {
    // The anonymous-signed-out path throws the `Not authenticated` sentinel;
    // treat that as silent-null. Any other rejection (real SDK failure) is
    // logged so the symptom is debuggable — see `feedback_correctness_over_dont_crash`.
    if (e instanceof Error && e.message === NOT_AUTHENTICATED_SENTINEL) {
      return null;
    }
    console.warn('[getTokenOrNull] token getter rejected:', e);
    return null;
  }
}
