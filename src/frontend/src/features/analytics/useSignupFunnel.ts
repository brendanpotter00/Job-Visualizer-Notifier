import { useEffect } from 'react';
import { useAuth } from '../auth/useAuth';
import { POSTHOG_CONFIG } from '../../config/posthog';
import { setAuthStateProperty, trackSignupFunnelLanding } from './events';

// Module-level guard so the landing event fires at most once per full page load — even
// across React StrictMode's double-invoke and SPA route changes (a client-side route
// change is not a new "landing"). A full reload resets this naturally, which is the
// intended behaviour: a reload is a fresh visit for funnel purposes. Kept in memory (no
// storage) to preserve the cookieless-before-consent guarantee.
let landingFired = false;

// Module-level guard recording whether this page load was EVER observed authenticated. Set
// the instant auth resolves to signed-in, it suppresses the landing if the visitor later
// signs out IN-PAGE (Google One-Tap `logout()` = `setGoogleCredential(null)`, no reload — so
// `isAuthenticated` flips true→false and the effect re-runs). Without it that re-run would
// schedule the grace timer and fire `signup_funnel_landing` for someone who already had an
// account, violating the "can't count people that already have an account" invariant.
// Cookieless residual: an Auth0 `logout()` does a FULL page reload, which resets this module
// — a post-logout anonymous visit is then indistinguishable from a never-had-an-account
// visitor and will be counted. That's unavoidable without device storage, and accepted.
let sessionWasAuthenticated = false;

// Grace period before firing the landing event. Returning users whose session is being
// silently restored (Auth0 silent-auth, or Google One-Tap `auto_select`) start a load as
// unauthenticated and only flip to authenticated a beat later. Waiting briefly — and
// cancelling the moment auth flips true — keeps those existing account-holders OUT of the
// denominator, which is the "don't count people who already have an account" requirement.
// The cost is that visitors who bounce within this window aren't counted; that's
// acceptable since they're not real signup candidates. Tunable.
const LANDING_GRACE_MS = 2500;

/**
 * Test-only: reset the once-per-load guards between cases. Not used in app code.
 */
export function __resetSignupFunnelLandingForTests(): void {
  landingFired = false;
  sessionWasAuthenticated = false;
}

/**
 * Top of the signup-conversion funnel.
 *
 * Fires `signup_funnel_landing` at most once per page load, but ONLY after auth has
 * resolved AND the visitor is not — and was never — authenticated during this page load.
 * Returning signed-in users are excluded by construction (the event never fires while
 * authenticated), and a visitor who was authenticated earlier in the same load and then
 * signs out in-page is suppressed too — both satisfy the "can't count people that already
 * have an account" requirement. (Cookieless residual: an Auth0 `logout()` full reload resets
 * the module, so a post-logout anonymous visit looks like a fresh never-had-an-account
 * visitor — unavoidable without device storage; see `sessionWasAuthenticated` above.)
 *
 * Also keeps the `is_authenticated` super-property in sync with auth state so every
 * captured event (pageviews, CTA clicks) can be sliced by whether the visitor was signed
 * in. This is the single owner of that super-property.
 *
 * Mounted once at the app root (App.tsx), alongside usePostHogPageview / usePostHogIdentify.
 */
export function useSignupFunnel(): void {
  const { isEnabled: authEnabled, isLoading, isAuthenticated } = useAuth();

  useEffect(() => {
    if (!POSTHOG_CONFIG.isEnabled) return;
    // Wait for auth to resolve before deciding — otherwise a returning signed-in user's
    // landing could be miscounted during the brief pre-auth window. When auth is disabled
    // entirely, every visitor is anonymous and `isLoading` is already false.
    if (authEnabled && isLoading) return;

    setAuthStateProperty(isAuthenticated);

    if (isAuthenticated) {
      // Returning signed-in visitor — not a funnel entry. Remember it so an in-page
      // sign-out later in this same load isn't miscounted as a fresh landing.
      sessionWasAuthenticated = true;
      return;
    }
    if (landingFired) return;
    if (sessionWasAuthenticated) return; // signed out in-page this load — already had an account

    // Defer briefly so a returning user whose session is still being silently restored
    // flips to authenticated first (which re-runs this effect, clears the timer below via
    // cleanup, and hits the `isAuthenticated` early-return) and is never counted.
    const timer = window.setTimeout(() => {
      landingFired = true;
      trackSignupFunnelLanding({
        landing_path: window.location.pathname,
        referrer: document.referrer || '',
      });
    }, LANDING_GRACE_MS);
    return () => window.clearTimeout(timer);
  }, [authEnabled, isLoading, isAuthenticated]);
}
