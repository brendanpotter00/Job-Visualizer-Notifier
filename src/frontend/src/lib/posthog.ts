import posthog from 'posthog-js';
import { POSTHOG_CONFIG } from '../config/posthog';

// Initialize once at module scope so React StrictMode double-invoke
// and provider remounts don't create duplicate PostHog instances.
if (POSTHOG_CONFIG.isEnabled) {
  posthog.init(POSTHOG_CONFIG.key, {
    api_host: POSTHOG_CONFIG.apiHost,
    ui_host: POSTHOG_CONFIG.uiHost,
    defaults: '2026-05-30',
    // Capture nothing and write no cookies until the user opts in via the consent banner.
    opt_out_capturing_by_default: true,
    persistence: 'memory',
    capture_pageview: false,
    disable_session_recording: true,
    session_recording: {
      maskAllInputs: true,
    },
  });
}

export { posthog };
