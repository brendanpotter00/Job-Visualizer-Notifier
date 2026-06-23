import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import posthog from 'posthog-js';
import { CookieConsentBanner } from '../../../components/shared/CookieConsentBanner';

// Make the banner visible by returning a real project key.
vi.mock('../../../config/posthog', () => ({
  POSTHOG_CONFIG: {
    key: 'phc_test',
    apiHost: '/ingest',
    uiHost: 'https://us.posthog.com',
    isEnabled: true,
  },
}));

describe('CookieConsentBanner', () => {
  beforeEach(() => {
    vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('pending' as never);
    vi.clearAllMocks();
    vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('pending' as never);
  });

  it('renders the banner when consent is pending', () => {
    render(<CookieConsentBanner />);
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /decline/i })).toBeInTheDocument();
  });

  it('does not render when consent is already granted', () => {
    vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('granted' as never);
    render(<CookieConsentBanner />);
    expect(screen.queryByRole('button', { name: /accept/i })).not.toBeInTheDocument();
  });

  it('does not render when consent is already denied', () => {
    vi.mocked(posthog.get_explicit_consent_status).mockReturnValue('denied' as never);
    render(<CookieConsentBanner />);
    expect(screen.queryByRole('button', { name: /accept/i })).not.toBeInTheDocument();
  });

  it('calls opt_in helpers and hides banner when Accept is clicked', async () => {
    const user = userEvent.setup();
    render(<CookieConsentBanner />);
    await user.click(screen.getByRole('button', { name: /accept/i }));
    expect(posthog.set_config).toHaveBeenCalledWith({ persistence: 'localStorage+cookie' });
    expect(posthog.opt_in_capturing).toHaveBeenCalled();
    expect(posthog.startSessionRecording).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /accept/i })).not.toBeInTheDocument();
  });

  it('calls opt_out and hides banner when Decline is clicked', async () => {
    const user = userEvent.setup();
    render(<CookieConsentBanner />);
    await user.click(screen.getByRole('button', { name: /decline/i }));
    expect(posthog.opt_out_capturing).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /decline/i })).not.toBeInTheDocument();
  });
});
