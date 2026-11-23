import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { hasStoredAuthSession } from '../../app/homeDestination';
import { AUTH_CONFIG } from '../../config/auth';
import { useAuth } from '../../features/auth/useAuth';
import { useCurrentUser } from '../../features/auth/useCurrentUser';
import { useGoogleCredential } from '../../features/auth/useGoogleCredential';
import { isOnboardingExcludedPath } from './onboardingModel';
import { isRememberedAsAnswered, rememberAsAnswered, signInSubject } from './onboardingMemory';

/**
 * The longest a page is held for the answer. A profile request that hangs must
 * never trap a reader behind a loading screen: past this the page renders, and
 * the questions can still open over it if the answer arrives later.
 */
export const MAX_ONBOARDING_HOLD_MS = 6_000;

/**
 * True while `RootLayout` must hold the page because the first-sign-in
 * questions may be about to open and the server has not said yet.
 *
 * The 2026-11-23 bug: a brand-new account landed on Recent Jobs, watched it
 * load, and only then had the questions snap in over it — the gate opens on the
 * server's `onboardingCompletedAt === null`, and until `GET /api/users` came
 * back the layout rendered the page as if nothing would. Holding until that
 * answer is in means a new account goes from the sign-in loading screen
 * straight to the questions.
 *
 * Held only when ALL of these hold:
 * - signed in (or Auth0 is still restoring a stored session, the same wait
 *   `HomeRoute` makes), not the QA bypass, on a page the questions can open on;
 * - the current user is not loaded yet and did not fail (a failure releases at
 *   once: an unknown stamp never opens the questions);
 * - this browser has not already seen this account stamped
 *   (`onboardingMemory`), so a returning reader's page renders at once;
 * - for at most {@link MAX_ONBOARDING_HOLD_MS};
 * - this layout has not rendered the page yet. Once released it stays released,
 *   so a later sign-in or profile retry never swaps a page in use for the
 *   loading screen.
 *
 * Also records the account as answered once the server says it is stamped
 * (on load, or when the gate stamps it locally after a save).
 */
export function useOnboardingHold(): boolean {
  const { isAuthenticated, isLoading, user: auth0User } = useAuth();
  const { googleCredential } = useGoogleCredential();
  const { user, error } = useCurrentUser();
  const { pathname } = useLocation();
  const [hasStoredSession] = useState(() => hasStoredAuthSession());

  const subject = signInSubject(auth0User?.sub, googleCredential);
  // Only the row of THIS sign-in counts: never remember a subject against a
  // row still left over from another account.
  const answered =
    subject !== null &&
    user?.providerSubject === subject &&
    typeof user.onboardingCompletedAt === 'string';

  useEffect(() => {
    if (answered && subject) rememberAsAnswered(subject);
  }, [answered, subject]);

  const undecided =
    (isAuthenticated || (isLoading && hasStoredSession)) &&
    !AUTH_CONFIG.bypassEnabled &&
    !isOnboardingExcludedPath(pathname) &&
    user === null &&
    error === null;
  const wouldHold = undecided && !(subject !== null && isRememberedAsAnswered(subject));

  const [released, setReleased] = useState(false);
  if (!wouldHold && !released) setReleased(true);
  useEffect(() => {
    if (!wouldHold) return;
    const timer = window.setTimeout(() => setReleased(true), MAX_ONBOARDING_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [wouldHold]);

  return wouldHold && !released;
}
