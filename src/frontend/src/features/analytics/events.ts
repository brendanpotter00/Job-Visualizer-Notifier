import { posthog } from '../../lib/posthog';
import { POSTHOG_CONFIG } from '../../config/posthog';

/**
 * Signup-conversion funnel event taxonomy.
 *
 * One module owns every custom funnel event so the names live in exactly one place and
 * the call sites stay type-safe. The funnel that consumes these events is:
 *
 *   signup_funnel_landing  (denominator: an account-less visitor reached the app)
 *     → signin_cta_clicked (engagement: clicked a sign-in CTA, attributed by `location`)
 *       → user_signed_up   (conversion: fired server-side, only for brand-new accounts)
 *
 * `user_signed_up` is captured by the backend (src/backend/api/routers/users.py) with
 * `distinct_id = auth0_id`, and the frontend `identify(providerSubject)` uses that same
 * subject. The PRIMARY metric is the aggregate count ratio (number of
 * `signup_funnel_landing` events vs number of `user_signed_up` events), which needs no
 * per-person link. A per-person landing→signup stitch is only a best-effort bonus: with
 * `persistence: 'memory'` the anonymous distinct_id lives in memory and is discarded by the
 * Auth0 full-page redirect (`login()` = `loginWithRedirect()`), so a pre-redirect landing
 * is orphaned and does NOT merge into the identified person. The stitch holds only when the
 * visitor accepted consent before signing in (id persisted) or used in-page Google One-Tap
 * (no reload). See lib/posthog.ts for the trade-off.
 *
 * Every capture is best-effort and gated on `POSTHOG_CONFIG.isEnabled`: when
 * `VITE_POSTHOG_KEY` is unset PostHog is never initialised, so these become no-ops (mirrors
 * the analytics hooks). A capture that throws is swallowed (dev-warned) — analytics must
 * never throw into a call site, several of which fire immediately before `login()`.
 */

/**
 * Which surface a sign-in call-to-action was triggered from.
 *
 * Google One-Tap is intentionally absent: its success callback also fires for the silent
 * `auto_select` re-auth of returning users, which can't be told apart from a genuine
 * new-user tap, so counting it as a CTA click would be noise. One-Tap signups are still
 * captured (server-side `user_signed_up`) and attributed via the signup-provider split.
 */
export type SignInLocation = 'appbar' | 'job_overlay' | 'edit_prefs_link' | 'account_page';

/** Which surface showed the signed-out sign-in overlay. */
export type OverlayPage = 'recent' | 'companies' | 'bucket_modal';

/**
 * Run an analytics side-effect best-effort. Analytics must NEVER throw into a call site:
 * several callers invoke a tracker immediately before `useAuth().login()` (the primary
 * sign-in CTA), so a thrown `posthog.capture` would block or mislabel sign-in. We swallow
 * the throw but surface it via `console.warn` in dev so failures stay observable rather
 * than vanishing silently.
 */
function safeAnalytics(run: () => void): void {
  try {
    run();
  } catch (err) {
    if (import.meta.env.DEV) {
      console.warn('[analytics] capture failed (non-fatal):', err);
    }
  }
}

/**
 * Top of the funnel: an account-less visitor reached the app (auth has resolved and they
 * are not signed in). Existing account-holders never reach this call by construction, so
 * they are excluded from the denominator — the "don't count people who already have an
 * account" requirement. Fired at most once per page load (see useSignupFunnel).
 */
export function trackSignupFunnelLanding(props: { landing_path: string; referrer: string }): void {
  if (!POSTHOG_CONFIG.isEnabled) return;
  safeAnalytics(() => posthog.capture('signup_funnel_landing', props));
}

/**
 * Mid-funnel: an unauthenticated visitor clicked a sign-in CTA. `location` attributes the
 * click to a surface so the funnel can show which CTA actually drives signups, and the
 * `signin_cta_clicked → user_signed_up` step exposes the Auth0-redirect drop-off.
 */
export function trackSignInClick(location: SignInLocation): void {
  if (!POSTHOG_CONFIG.isEnabled) return;
  safeAnalytics(() => posthog.capture('signin_cta_clicked', { location }));
}

/** The signed-out job-list overlay (after the free-job limit) first became visible. */
export function trackSignInOverlayViewed(page: OverlayPage): void {
  if (!POSTHOG_CONFIG.isEnabled) return;
  safeAnalytics(() => posthog.capture('signin_overlay_viewed', { page }));
}

/**
 * Register `is_authenticated` as a super-property so it rides on every captured event.
 * Lets the funnel filter the landing/pageview steps to genuinely-anonymous traffic and
 * slice any event by auth state. Set as a super-property (persists for the session)
 * rather than threaded through each call site.
 */
export function setAuthStateProperty(isAuthenticated: boolean): void {
  if (!POSTHOG_CONFIG.isEnabled) return;
  safeAnalytics(() => posthog.register({ is_authenticated: isAuthenticated }));
}
