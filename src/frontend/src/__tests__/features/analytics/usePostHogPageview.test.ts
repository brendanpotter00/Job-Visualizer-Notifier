import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

// Stable capture mock so we can assert calls.
const mockCapture = vi.fn();

vi.mock('@posthog/react', () => ({
  usePostHog: () => ({ capture: mockCapture }),
}));

vi.mock('../../../config/posthog', () => ({
  POSTHOG_CONFIG: { isEnabled: true },
}));

// Controlled pathname so we can change it between renders.
let mockPathname = '/';
let mockSearch = '';

vi.mock('react-router-dom', () => ({
  useLocation: () => ({ pathname: mockPathname, search: mockSearch }),
}));

import { usePostHogPageview } from '../../../features/analytics/usePostHogPageview';

describe('usePostHogPageview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = '/';
    mockSearch = '';
  });

  it('captures $pageview on initial render', () => {
    renderHook(() => usePostHogPageview());
    expect(mockCapture).toHaveBeenCalledWith('$pageview', expect.objectContaining({ $current_url: expect.any(String) }));
  });

  it('captures $pageview again when pathname changes', () => {
    const { rerender } = renderHook(() => usePostHogPageview());
    expect(mockCapture).toHaveBeenCalledTimes(1);
    mockPathname = '/companies';
    rerender();
    expect(mockCapture).toHaveBeenCalledTimes(2);
  });

  it('does not capture when PostHog is disabled', async () => {
    // Re-load the hook against a fresh module graph where POSTHOG_CONFIG
    // reports isEnabled: false, so the hook hits its early-return guard.
    vi.resetModules();
    vi.doMock('../../../config/posthog', () => ({
      POSTHOG_CONFIG: { isEnabled: false },
    }));
    vi.doMock('@posthog/react', () => ({
      usePostHog: () => ({ capture: mockCapture }),
    }));
    vi.doMock('react-router-dom', () => ({
      useLocation: () => ({ pathname: mockPathname, search: mockSearch }),
    }));

    const { usePostHogPageview: usePostHogPageviewDisabled } = await import(
      '../../../features/analytics/usePostHogPageview'
    );

    renderHook(() => usePostHogPageviewDisabled());
    expect(mockCapture).not.toHaveBeenCalled();

    vi.doUnmock('../../../config/posthog');
    vi.doUnmock('@posthog/react');
    vi.doUnmock('react-router-dom');
    vi.resetModules();
  });
});
