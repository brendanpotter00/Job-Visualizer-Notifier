import '@testing-library/jest-dom';
import { expect, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import * as matchers from '@testing-library/jest-dom/matchers';

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
