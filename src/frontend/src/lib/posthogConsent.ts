import { posthog } from './posthog';

export type ConsentStatus = 'pending' | 'granted' | 'denied';

export function getConsentStatus(): ConsentStatus {
  return posthog.get_explicit_consent_status() as ConsentStatus;
}

export function acceptTracking(): void {
  posthog.set_config({ persistence: 'localStorage+cookie' });
  posthog.opt_in_capturing();
  posthog.startSessionRecording();
  posthog.capture('$pageview');
}

export function declineTracking(): void {
  posthog.opt_out_capturing();
}
