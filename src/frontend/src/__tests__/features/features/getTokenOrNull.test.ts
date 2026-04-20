import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getTokenOrNull,
  registerTokenGetter,
} from '../../../features/features/getTokenOrNull';

describe('getTokenOrNull', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    // Reset the module-scoped getter between tests to avoid cross-test leakage.
    registerTokenGetter(null);
  });

  afterEach(() => {
    registerTokenGetter(null);
    warnSpy.mockRestore();
  });

  it('returns null and does NOT warn when no getter is registered', async () => {
    await expect(getTokenOrNull()).resolves.toBeNull();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('returns the token string when the registered getter resolves', async () => {
    registerTokenGetter(async () => 'tok-abc');
    await expect(getTokenOrNull()).resolves.toBe('tok-abc');
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('returns null silently when the getter throws the "Not authenticated" sentinel (normal signed-out path)', async () => {
    // Matches `useAuth().getToken()`'s signed-out throw in
    // features/auth/useAuth.ts. This fires on every anonymous page load and
    // must NOT produce a warn log, else the console is spammed for the
    // expected steady-state anonymous flow.
    registerTokenGetter(async () => {
      throw new Error('Not authenticated');
    });
    await expect(getTokenOrNull()).resolves.toBeNull();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('returns null AND warns when the getter throws a non-sentinel Error (real SDK failure)', async () => {
    // Real SDK failures (network, token refresh, misconfig) must surface so
    // the symptom is debuggable — per `feedback_correctness_over_dont_crash`.
    registerTokenGetter(async () => {
      throw new Error('Network request failed');
    });
    await expect(getTokenOrNull()).resolves.toBeNull();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      '[getTokenOrNull] token getter rejected:',
      expect.any(Error)
    );
  });

  it('returns null AND warns when the getter rejects with a non-Error value', async () => {
    // A non-Error rejection (e.g. a plain object from a broken SDK) cannot
    // match the sentinel by construction, so it must warn. Use
    // `Promise.reject` directly so this doesn't rely on `throw` of a literal.
    const rejection = { kind: 'broken-sdk' };
    registerTokenGetter(() => Promise.reject(rejection));
    await expect(getTokenOrNull()).resolves.toBeNull();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      '[getTokenOrNull] token getter rejected:',
      rejection
    );
  });
});
