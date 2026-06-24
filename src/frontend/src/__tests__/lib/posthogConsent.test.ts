import { describe, it, expect, vi, beforeEach } from 'vitest';
import posthog from 'posthog-js';
import { getConsentStatus, acceptTracking, declineTracking } from '../../lib/posthogConsent';

describe('posthogConsent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('pending' as never);
  });

  describe('getConsentStatus', () => {
    it('returns pending when no decision has been made', () => {
      vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('pending' as never);
      expect(getConsentStatus()).toBe('pending');
    });

    it('returns granted after opt-in', () => {
      vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('granted' as never);
      expect(getConsentStatus()).toBe('granted');
    });

    it('returns denied after opt-out', () => {
      vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('denied' as never);
      expect(getConsentStatus()).toBe('denied');
    });
  });

  describe('acceptTracking', () => {
    it('switches persistence, opts in, starts recording, and captures pageview', () => {
      acceptTracking();
      expect(posthog.set_config).toHaveBeenCalledWith({ persistence: 'localStorage+cookie' });
      expect(posthog.opt_in_capturing).toHaveBeenCalled();
      expect(posthog.startSessionRecording).toHaveBeenCalled();
      expect(posthog.capture).toHaveBeenCalledWith('$pageview');
    });
  });

  describe('declineTracking', () => {
    it('opts out of capturing', () => {
      declineTracking();
      expect(posthog.opt_out_capturing).toHaveBeenCalled();
    });

    it('does not start recording or switch persistence', () => {
      declineTracking();
      expect(posthog.set_config).not.toHaveBeenCalled();
      expect(posthog.startSessionRecording).not.toHaveBeenCalled();
    });
  });
});
