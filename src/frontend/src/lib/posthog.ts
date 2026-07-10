import posthog from 'posthog-js';
import { POSTHOG_CONFIG } from '../config/posthog';

// Initialize once at module scope so React StrictMode double-invoke
// and provider remounts don't create duplicate PostHog instances.
if (POSTHOG_CONFIG.isEnabled) {
  posthog.init(POSTHOG_CONFIG.key, {
    api_host: POSTHOG_CONFIG.apiHost,
    ui_host: POSTHOG_CONFIG.uiHost,
    defaults: '2026-05-30',
    // Cookieless-by-default. We CAPTURE from the first page load so every visitor is
    // counted (the signup-funnel denominator), but `persistence: 'memory'` keeps the
    // distinct_id in memory only — no cookies or localStorage are written until the
    // user clicks Accept, at which point `acceptTracking()` upgrades persistence to
    // 'localStorage+cookie'. Clicking Decline opts out entirely (`declineTracking()`).
    // `get_explicit_consent_status()` ignores this default, so the consent banner still
    // shows until the user makes an explicit choice (see lib/posthogConsent.ts).
    opt_out_capturing_by_default: false,
    persistence: 'memory',
    // Anonymous events carry no person profile (lower cost); a profile is created on
    // `identify()`. PostHog only stitches prior anonymous events to that profile when the
    // anonymous distinct_id survives until identify — which, with `persistence: 'memory'`,
    // it does NOT across the Auth0 full-page redirect (`login()` = `loginWithRedirect()`):
    // the in-memory id is discarded on reload, so a pre-redirect landing is orphaned and
    // does NOT merge into the post-redirect person. The per-person landing→signup stitch
    // therefore holds ONLY when the visitor accepted consent before signing in (id persisted
    // to localStorage+cookie) or signs in via in-page Google One-Tap (no reload). The
    // PRIMARY funnel metric is the aggregate count ratio (number of `signup_funnel_landing`
    // events vs number of `user_signed_up` events), which does not depend on the stitch.
    person_profiles: 'identified_only',
    capture_pageview: false,
    disable_session_recording: true,
    session_recording: {
      maskAllInputs: true,
    },
  });
}

export { posthog };
