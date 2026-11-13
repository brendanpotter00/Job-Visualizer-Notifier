import { describe, it, expect } from 'vitest';
import {
  CONSTRAINED_BODY_COUNT,
  DESKTOP_BODY_COUNT,
  resolveExperienceTier,
  resolveFrameloop,
  type ExperienceTierInput,
} from '../../../../pages/LandingPage/prototypes/shared3d/experienceTier';

/** Capable desktop baseline; each test overrides one axis. */
const CAPABLE: ExperienceTierInput = {
  prefersReducedMotion: false,
  webglSupported: true,
  isMobileViewport: false,
  hardwareConcurrency: 10,
  deviceMemory: 8,
};

describe('resolveExperienceTier', () => {
  it('capable desktop → full tier, desktop body count, dpr 2', () => {
    expect(resolveExperienceTier(CAPABLE)).toEqual({
      tier: 'full',
      bodyCount: DESKTOP_BODY_COUNT,
      maxDpr: 2,
      compact: false,
    });
  });

  it('absent hardware hints read as capable (UA hides them, e.g. Safari)', () => {
    expect(
      resolveExperienceTier({
        ...CAPABLE,
        hardwareConcurrency: undefined,
        deviceMemory: undefined,
      })
    ).toEqual({ tier: 'full', bodyCount: DESKTOP_BODY_COUNT, maxDpr: 2, compact: false });
  });

  it('prefers-reduced-motion forces the fallback tier on any hardware', () => {
    expect(resolveExperienceTier({ ...CAPABLE, prefersReducedMotion: true })).toEqual({
      tier: 'fallback',
      bodyCount: CONSTRAINED_BODY_COUNT,
      maxDpr: 1,
      compact: false,
    });
  });

  it('missing WebGL forces the fallback tier on any hardware', () => {
    expect(resolveExperienceTier({ ...CAPABLE, webglSupported: false })).toEqual({
      tier: 'fallback',
      bodyCount: CONSTRAINED_BODY_COUNT,
      maxDpr: 1,
      compact: false,
    });
  });

  it('reduced motion beats low-end signals (fallback, not constrained-full)', () => {
    expect(
      resolveExperienceTier({
        ...CAPABLE,
        prefersReducedMotion: true,
        isMobileViewport: true,
        hardwareConcurrency: 2,
      }).tier
    ).toBe('fallback');
  });

  // Phones were the static grid from 2026-09-10 until the owner asked for the
  // pile back (2026-11-12): a capable phone gets the full tier, framed compact
  // (camera pulled back so tiles render at the grid's size), with the
  // constrained roster so the pile fits the band under the CTAs.
  it('mobile viewport on capable hardware → full compact tier, constrained roster, dpr 2', () => {
    expect(
      resolveExperienceTier({ ...CAPABLE, isMobileViewport: true, hardwareConcurrency: 12 })
    ).toEqual({
      tier: 'full',
      bodyCount: CONSTRAINED_BODY_COUNT,
      maxDpr: 2,
      compact: true,
    });
  });

  it('mobile viewport on low-end hardware → full compact tier with the lower dpr cap', () => {
    expect(resolveExperienceTier({ ...CAPABLE, isMobileViewport: true, deviceMemory: 2 })).toEqual({
      tier: 'full',
      bodyCount: CONSTRAINED_BODY_COUNT,
      maxDpr: 1.5,
      compact: true,
    });
  });

  it('a phone without WebGL still gets the DOM fallback (never compact)', () => {
    expect(
      resolveExperienceTier({ ...CAPABLE, isMobileViewport: true, webglSupported: false })
    ).toEqual({
      tier: 'fallback',
      bodyCount: CONSTRAINED_BODY_COUNT,
      maxDpr: 1,
      compact: false,
    });
  });

  it.each([
    ['hardwareConcurrency 4 (boundary)', { hardwareConcurrency: 4 }, CONSTRAINED_BODY_COUNT],
    ['hardwareConcurrency 2', { hardwareConcurrency: 2 }, CONSTRAINED_BODY_COUNT],
    ['hardwareConcurrency 5 (just above)', { hardwareConcurrency: 5 }, DESKTOP_BODY_COUNT],
    ['deviceMemory 4 (boundary)', { deviceMemory: 4 }, CONSTRAINED_BODY_COUNT],
    ['deviceMemory 2', { deviceMemory: 2 }, CONSTRAINED_BODY_COUNT],
    ['deviceMemory 8', { deviceMemory: 8 }, DESKTOP_BODY_COUNT],
  ] as const)('%s → bodyCount %i', (_label, overrides, expectedBodies) => {
    const result = resolveExperienceTier({ ...CAPABLE, ...overrides });
    expect(result.tier).toBe('full');
    expect(result.bodyCount).toBe(expectedBodies);
    expect(result.maxDpr).toBe(expectedBodies === DESKTOP_BODY_COUNT ? 2 : 1.5);
    expect(result.compact).toBe(false);
  });
});

describe('resolveFrameloop', () => {
  it.each([
    [{ allAsleep: false, heroInView: true, docVisible: true }, 'always'],
    [{ allAsleep: true, heroInView: true, docVisible: true }, 'never'],
    [{ allAsleep: false, heroInView: false, docVisible: true }, 'never'],
    [{ allAsleep: false, heroInView: true, docVisible: false }, 'never'],
    [{ allAsleep: true, heroInView: false, docVisible: true }, 'never'],
    [{ allAsleep: true, heroInView: true, docVisible: false }, 'never'],
    [{ allAsleep: false, heroInView: false, docVisible: false }, 'never'],
    [{ allAsleep: true, heroInView: false, docVisible: false }, 'never'],
  ] as const)('%o → %s', (input, expected) => {
    expect(resolveFrameloop(input)).toBe(expected);
  });
});
