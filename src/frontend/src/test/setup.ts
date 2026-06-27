import '@testing-library/jest-dom';
import { expect, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';

// Stub out PostHog SDK so tests run without a real API key and without
// network calls. Individual test files can override specific methods via vi.mocked().
vi.mock('posthog-js', () => ({
  default: {
    init: vi.fn(),
    capture: vi.fn(),
    identify: vi.fn(),
    reset: vi.fn(),
    register: vi.fn(),
    opt_in_capturing: vi.fn(),
    opt_out_capturing: vi.fn(),
    set_config: vi.fn(),
    startSessionRecording: vi.fn(),
    get_explicit_consent_status: vi.fn(() => 'pending'),
    has_opted_in_capturing: vi.fn(() => false),
    has_opted_out_capturing: vi.fn(() => false),
  },
}));

vi.mock('@posthog/react', () => ({
  PostHogProvider: vi.fn(({ children }: { children: unknown }) => children),
  usePostHog: () => ({
    capture: vi.fn(),
    identify: vi.fn(),
    reset: vi.fn(),
  }),
}));

expect.extend(matchers);

// jsdom does not implement IntersectionObserver. Provide a no-op default so any
// component using infinite scroll (e.g. RecentJobsList, ChangelogColumn) can
// render without crashing. Tests that need to drive the observer reassign
// `global.IntersectionObserver` with a capturing mock.
if (!('IntersectionObserver' in globalThis)) {
  class NoopIntersectionObserver {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    takeRecords = vi.fn(() => []);
    root = null;
    rootMargin = '';
    thresholds = [];
  }
  globalThis.IntersectionObserver =
    NoopIntersectionObserver as unknown as typeof IntersectionObserver;
}

afterEach(() => {
  cleanup();
});
