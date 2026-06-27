import { describe, it, expect, vi, beforeEach } from 'vitest';
import posthog from 'posthog-js';

// `events.ts` captures through the module-scope posthog singleton (lib/posthog.ts
// re-exports the posthog-js default), so the global posthog-js mock in test/setup.ts
// receives the calls. Enable analytics so the isEnabled guard does not short-circuit.
vi.mock('../../../config/posthog', () => ({
  POSTHOG_CONFIG: { isEnabled: true },
}));

import {
  trackSignupFunnelLanding,
  trackSignInClick,
  trackSignInOverlayViewed,
  setAuthStateProperty,
} from '../../../features/analytics/events';

describe('analytics/events (enabled)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('trackSignupFunnelLanding captures signup_funnel_landing with path + referrer', () => {
    trackSignupFunnelLanding({ landing_path: '/jobs', referrer: 'https://news.example' });
    expect(posthog.capture).toHaveBeenCalledWith('signup_funnel_landing', {
      landing_path: '/jobs',
      referrer: 'https://news.example',
    });
  });

  it('trackSignInClick captures signin_cta_clicked with the CTA location', () => {
    trackSignInClick('job_overlay');
    expect(posthog.capture).toHaveBeenCalledWith('signin_cta_clicked', { location: 'job_overlay' });
  });

  it('trackSignInOverlayViewed captures signin_overlay_viewed with the page', () => {
    trackSignInOverlayViewed('companies');
    expect(posthog.capture).toHaveBeenCalledWith('signin_overlay_viewed', { page: 'companies' });
  });

  it('setAuthStateProperty registers is_authenticated as a super-property', () => {
    setAuthStateProperty(true);
    expect(posthog.register).toHaveBeenCalledWith({ is_authenticated: true });
    setAuthStateProperty(false);
    expect(posthog.register).toHaveBeenCalledWith({ is_authenticated: false });
  });
});

describe('analytics/events (disabled)', () => {
  it('every tracker is a no-op when PostHog is disabled', async () => {
    vi.resetModules();
    vi.doMock('../../../config/posthog', () => ({
      POSTHOG_CONFIG: { isEnabled: false },
    }));
    const events = await import('../../../features/analytics/events');
    vi.clearAllMocks();

    events.trackSignupFunnelLanding({ landing_path: '/', referrer: '' });
    events.trackSignInClick('appbar');
    events.trackSignInOverlayViewed('recent');
    events.setAuthStateProperty(true);

    expect(posthog.capture).not.toHaveBeenCalled();
    expect(posthog.register).not.toHaveBeenCalled();

    vi.doUnmock('../../../config/posthog');
    vi.resetModules();
  });
});
