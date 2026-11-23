/**
 * This browser's memory of which accounts have ALREADY answered (or skipped)
 * the first-sign-in questions.
 *
 * Why it exists: on a page load the app does not know whether the reader must
 * be asked until `GET /api/users` returns, and showing the page in the
 * meantime is exactly the bug it fixes — a brand-new account watched Recent
 * Jobs load, then the questions snapped in over it. So `RootLayout` holds the
 * page until the answer is in (`useOnboardingHold`). Holding EVERY signed-in
 * load for one round trip would slow every returning reader to fix a screen
 * each account sees once, so an account this browser has seen stamped is not
 * held once its subject is known: the page renders at once, exactly as before.
 * (While Auth0 is still restoring a stored session the subject is not known
 * yet, so `useOnboardingHold` holds every account for that short wait — the
 * same wait `HomeRoute` makes.)
 *
 * Only a performance hint. The server's `onboarding_completed_at` stays the
 * one source of truth — the gate still opens on `null` whatever this says, and
 * an account missing from it (a new device, cleared storage) is merely held
 * for one round trip.
 *
 * Keyed by the sign-in subject the browser already holds before any request,
 * spelled the way the backend stores it (`User.providerSubject`). See
 * {@link signInSubject}.
 */

const STORAGE_KEY = 'jvn.onboardingAnswered.v1';
/** The backend's `GOOGLE_ISSUERS`: a One-Tap `sub` from these gets the `google|` prefix. */
const GOOGLE_ISSUERS = new Set(['accounts.google.com', 'https://accounts.google.com']);
/** Enough for a shared computer; the oldest entry drops first. */
const MAX_REMEMBERED = 20;

function storage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

function readRemembered(store: Storage | undefined): string[] {
  if (!store) return [];
  try {
    const parsed: unknown = JSON.parse(store.getItem(STORAGE_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

/** True when this browser has seen `subject`'s account stamped. */
export function isRememberedAsAnswered(
  subject: string,
  store: Storage | undefined = storage()
): boolean {
  return readRemembered(store).includes(subject);
}

/** Record that `subject`'s account is stamped. Storage failures are ignored: it is only a hint. */
export function rememberAsAnswered(subject: string, store: Storage | undefined = storage()): void {
  if (!store) return;
  const current = readRemembered(store);
  if (current.includes(subject)) return;
  const next = [...current, subject].slice(-MAX_REMEMBERED);
  try {
    store.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Quota / private mode: the reader is held for one round trip next time.
  }
}

/**
 * The signed-in identity as the browser knows it before any request, spelled
 * like the backend's `User.providerSubject` (`get_normalized_subject` in
 * `src/backend/api/auth/jwt.py`): the Auth0 user's `sub` as is; for a Google
 * One-Tap credential (a JWT), its `sub` prefixed `google|` when Google issued
 * it, as is otherwise. `null` when neither is readable.
 */
export function signInSubject(
  auth0Sub: string | undefined,
  googleCredential: string | null
): string | null {
  if (auth0Sub) return auth0Sub;
  if (!googleCredential) return null;
  try {
    const payload = googleCredential.split('.')[1];
    if (!payload) return null;
    const json = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/'))) as {
      sub?: unknown;
      iss?: unknown;
    };
    if (typeof json.sub !== 'string' || !json.sub) return null;
    return typeof json.iss === 'string' && GOOGLE_ISSUERS.has(json.iss)
      ? `google|${json.sub}`
      : json.sub;
  } catch {
    return null;
  }
}
