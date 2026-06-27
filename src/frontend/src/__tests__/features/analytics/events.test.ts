import { describe, it, expect, vi, beforeEach } from 'vitest';
import posthog from 'posthog-js';

// Mutable config object so we can flip `isEnabled` between tests WITHOUT resetting
// modules. Resetting modules would re-instantiate the posthog-js mock, leaving the
// `posthog` reference imported here pointing at a different instance than the one
// events.ts calls — which made the old "disabled" test vacuous (it asserted against a
// stale mock and would pass even if the isEnabled guard were deleted). Because the
// `events.ts` helpers read `POSTHOG_CONFIG.isEnabled` at call time, mutating this object
// is observed by the same loaded module instance.
const { mockConfig } = vi.hoisted(() => ({ mockConfig: { isEnabled: true } }));
vi.mock('../../../config/posthog', () => ({
  POSTHOG_CONFIG: mockConfig,
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
    mockConfig.isEnabled = true;
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
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig.isEnabled = false;
  });

  // Non-vacuous: this asserts on the SAME posthog mock that events.ts calls, so deleting
  // the `if (!POSTHOG_CONFIG.isEnabled) return;` guard would make these expectations fail.
  it('every tracker is a no-op when PostHog is disabled', () => {
    trackSignupFunnelLanding({ landing_path: '/', referrer: '' });
    trackSignInClick('appbar');
    trackSignInOverlayViewed('recent');
    setAuthStateProperty(true);

    expect(posthog.capture).not.toHaveBeenCalled();
    expect(posthog.register).not.toHaveBeenCalled();
  });
});

describe('analytics/events (best-effort)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig.isEnabled = true;
  });

  // F2: analytics must never throw into a call site (several fire right before login()).
  it('swallows a capture that throws instead of propagating it', () => {
    vi.mocked(posthog.capture).mockImplementationOnce(() => {
      throw new Error('capture boom');
    });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    expect(() => trackSignInClick('appbar')).not.toThrow();
    // Failures stay observable in dev rather than vanishing silently.
    if (import.meta.env.DEV) {
      expect(warn).toHaveBeenCalled();
    }

    warn.mockRestore();
  });

  it('swallows a register that throws instead of propagating it', () => {
    vi.mocked(posthog.register).mockImplementationOnce(() => {
      throw new Error('register boom');
    });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    expect(() => setAuthStateProperty(true)).not.toThrow();

    warn.mockRestore();
  });
});
