import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const mockTrackLanding = vi.fn();
const mockSetAuthState = vi.fn();

// Mutable so a test can flip `isEnabled` and exercise the no-op early-return without
// resetting modules. The hook reads `POSTHOG_CONFIG.isEnabled` at effect-run time, so
// mutating this object is observed by the loaded hook.
const { mockPosthogConfig } = vi.hoisted(() => ({ mockPosthogConfig: { isEnabled: true } }));
vi.mock('../../../config/posthog', () => ({
  POSTHOG_CONFIG: mockPosthogConfig,
}));

vi.mock('../../../features/analytics/events', () => ({
  trackSignupFunnelLanding: (...args: unknown[]) => mockTrackLanding(...args),
  setAuthStateProperty: (...args: unknown[]) => mockSetAuthState(...args),
}));

let mockAuth = { isEnabled: true, isLoading: false, isAuthenticated: false };
vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuth,
}));

import {
  useSignupFunnel,
  __resetSignupFunnelLandingForTests,
} from '../../../features/analytics/useSignupFunnel';

// Must exceed LANDING_GRACE_MS in the hook.
const PAST_GRACE_MS = 5000;

describe('useSignupFunnel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    __resetSignupFunnelLandingForTests();
    mockAuth = { isEnabled: true, isLoading: false, isAuthenticated: false };
    mockPosthogConfig.isEnabled = true;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('fires signup_funnel_landing once for an account-less visitor after the grace period', () => {
    renderHook(() => useSignupFunnel());
    // Nothing fires synchronously — the landing waits out the grace window.
    expect(mockTrackLanding).not.toHaveBeenCalled();
    vi.advanceTimersByTime(PAST_GRACE_MS);
    expect(mockTrackLanding).toHaveBeenCalledTimes(1);
    expect(mockTrackLanding).toHaveBeenCalledWith(
      expect.objectContaining({ landing_path: expect.any(String), referrer: expect.any(String) })
    );
  });

  it('registers is_authenticated=false for an anonymous visitor', () => {
    renderHook(() => useSignupFunnel());
    expect(mockSetAuthState).toHaveBeenCalledWith(false);
  });

  it('does NOT fire for a returning signed-in visitor, and registers is_authenticated=true', () => {
    mockAuth = { isEnabled: true, isLoading: false, isAuthenticated: true };
    renderHook(() => useSignupFunnel());
    vi.advanceTimersByTime(PAST_GRACE_MS);
    expect(mockTrackLanding).not.toHaveBeenCalled();
    expect(mockSetAuthState).toHaveBeenCalledWith(true);
  });

  it('waits while auth is still loading and does not fire', () => {
    mockAuth = { isEnabled: true, isLoading: true, isAuthenticated: false };
    renderHook(() => useSignupFunnel());
    vi.advanceTimersByTime(PAST_GRACE_MS);
    expect(mockTrackLanding).not.toHaveBeenCalled();
  });

  it('cancels the landing if auth flips true during the grace period (silently-restored session)', () => {
    const { rerender } = renderHook(() => useSignupFunnel());
    // Returning user: session restored before the grace window elapses.
    mockAuth = { isEnabled: true, isLoading: false, isAuthenticated: true };
    rerender();
    vi.advanceTimersByTime(PAST_GRACE_MS);
    expect(mockTrackLanding).not.toHaveBeenCalled();
  });

  it('fires at most once per page load even across re-renders', () => {
    const { rerender } = renderHook(() => useSignupFunnel());
    vi.advanceTimersByTime(PAST_GRACE_MS);
    rerender();
    vi.advanceTimersByTime(PAST_GRACE_MS);
    expect(mockTrackLanding).toHaveBeenCalledTimes(1);
  });

  // Non-vacuous: with the guard present neither side-effect runs; deleting the
  // `if (!POSTHOG_CONFIG.isEnabled) return;` early-return would make setAuthState fire
  // (it is reached before the isAuthenticated/grace branches), failing this test.
  it('is a complete no-op when PostHog is disabled (guards the isEnabled early-return)', () => {
    mockPosthogConfig.isEnabled = false;
    renderHook(() => useSignupFunnel());
    vi.advanceTimersByTime(PAST_GRACE_MS);
    expect(mockSetAuthState).not.toHaveBeenCalled();
    expect(mockTrackLanding).not.toHaveBeenCalled();
  });
});
