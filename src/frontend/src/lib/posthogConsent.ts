import { posthog } from './posthog';

export type ConsentStatus = 'pending' | 'granted' | 'denied';

export function getConsentStatus(): ConsentStatus {
  return posthog.get_explicit_consent_status() as ConsentStatus;
}

export function acceptTracking(): void {
  // Upgrade from in-memory (cookieless) capture to persistent tracking: write the
  // distinct_id to localStorage+cookie so the visitor is recognised across sessions,
  // turn on session recording, and record the explicit opt-in so the banner stops
  // showing. We do NOT fire a manual '$pageview' here — under the cookieless-by-default
  // init the landing pageview already fired on load (usePostHogPageview), so re-firing
  // would double-count it.
  posthog.set_config({ persistence: 'localStorage+cookie' });
  posthog.opt_in_capturing();
  posthog.startSessionRecording();
}

export function declineTracking(): void {
  // Stop all capture and record the explicit opt-out so the banner doesn't reappear.
  // Visitors who never click either button are still counted via the cookieless,
  // in-memory capture from the init config — only an explicit Decline removes someone
  // from analytics entirely.
  posthog.opt_out_capturing();
}
