import { describe, it, expect, vi } from 'vitest';
import { readHardwareHints } from '../../../../pages/AdminLandingPrototypesPage/prototypes/shared3d/useExperienceTier';

describe('readHardwareHints', () => {
  it('reads both hints when the navigator exposes them', () => {
    const nav = { hardwareConcurrency: 8, deviceMemory: 4 } as unknown as Navigator;
    expect(readHardwareHints(nav)).toEqual({ hardwareConcurrency: 8, deviceMemory: 4 });
  });

  it('maps missing hints to undefined (Safari hides deviceMemory)', () => {
    const nav = { hardwareConcurrency: 8 } as unknown as Navigator;
    expect(readHardwareHints(nav)).toEqual({
      hardwareConcurrency: 8,
      deviceMemory: undefined,
    });
    expect(readHardwareHints({} as unknown as Navigator)).toEqual({
      hardwareConcurrency: undefined,
      deviceMemory: undefined,
    });
  });

  it('returns empty hints when there is no navigator at all', () => {
    // Passing undefined re-triggers the default parameter, so remove the
    // ambient navigator itself to reach the no-navigator branch.
    vi.stubGlobal('navigator', undefined);
    try {
      expect(readHardwareHints()).toEqual({});
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('defaults to the ambient navigator when called with no argument', () => {
    // jsdom exposes hardwareConcurrency (host-derived), never deviceMemory.
    const hints = readHardwareHints();
    expect(typeof hints.hardwareConcurrency).toBe('number');
    expect(hints.deviceMemory).toBeUndefined();
  });
});
