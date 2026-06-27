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
    // Anonymous pageviews are processed as anonymous events (no person profile, lower
    // cost). A person profile is created on `identify()` and the prior anonymous events
    // stitch to it — this is what connects an anonymous landing to its eventual backend
    // `user_signed_up` event (both keyed on the same provider subject).
    person_profiles: 'identified_only',
    capture_pageview: false,
    disable_session_recording: true,
    session_recording: {
      maskAllInputs: true,
    },
  });
}

export { posthog };
