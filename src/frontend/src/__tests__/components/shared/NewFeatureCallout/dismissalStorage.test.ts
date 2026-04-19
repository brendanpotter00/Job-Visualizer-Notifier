import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { isDismissed, markDismissed } from '../../../../components/shared/NewFeatureCallout/dismissalStorage';

const KEY = 'unit-test-callout';
const STORAGE_KEY = `newFeatureCallout:${KEY}:dismissed`;

describe('dismissalStorage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('round-trips set -> read', () => {
    expect(isDismissed(KEY)).toBe(false);
    markDismissed(KEY);
    expect(isDismissed(KEY)).toBe(true);
  });

  it('stores an ISO-8601 timestamp (not the literal "true")', () => {
    markDismissed(KEY);
    const raw = window.localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBe('true');
    expect(raw).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  });

  it('namespaces the key', () => {
    markDismissed(KEY);
    expect(window.localStorage.getItem(STORAGE_KEY)).not.toBeNull();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it('returns false for a missing key', () => {
    expect(isDismissed('never-set')).toBe(false);
  });

  it('returns false when localStorage.getItem throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled');
    });
    expect(isDismissed(KEY)).toBe(false);
  });

  it('does not throw when localStorage.setItem throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    expect(() => markDismissed(KEY)).not.toThrow();
  });

  it('treats an empty string as not-dismissed', () => {
    window.localStorage.setItem(STORAGE_KEY, '');
    expect(isDismissed(KEY)).toBe(false);
  });
});
