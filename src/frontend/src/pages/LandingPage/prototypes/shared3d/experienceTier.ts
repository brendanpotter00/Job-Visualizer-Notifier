/**
 * Pure decision tables for the 3D prototypes' degradation ladder and frameloop
 * governor. Every branch lives here (not in the scene JSX) so the full matrix
 * is unit-testable in jsdom without ever touching three.js.
 *
 * Ladder (PLAN.md "Degradation ladder"):
 *   full desktop → full constrained (fewer bodies, lower DPR)
 *   → full compact (a phone: constrained bodies, camera pulled back)
 *   → fallback (reduced-motion or no WebGL: DOM-only, scene chunk never loads).
 *
 * Phones were a fallback tier from 2026-09-10 to 2026-11-12: with the desktop
 * camera a tile is ~1/7 of the canvas height, so on a narrow canvas the pile
 * stacked seven tiles high and buried the copy. They are back on the full
 * tier with `compact: true`, which frames the camera so a tile renders at the
 * static grid's size (see GravityPrototype/compactFraming.ts) and the pile
 * settles in the band under the CTAs. Owner decision, 2026-11-12.
 */

export type ExperienceTier = 'full' | 'fallback';

export interface ExperienceTierInput {
  prefersReducedMotion: boolean;
  webglSupported: boolean;
  isMobileViewport: boolean;
  /** navigator.hardwareConcurrency; undefined when the UA hides it. */
  hardwareConcurrency?: number;
  /** navigator.deviceMemory (GiB); undefined outside Chromium. */
  deviceMemory?: number;
}

export interface ExperienceTierResult {
  tier: ExperienceTier;
  /** Physics bodies (Gravity) / roster tiles (fallback grid reuses it too). */
  bodyCount: number;
  /** Upper bound for the Canvas dpr clamp `[1, maxDpr]`. */
  maxDpr: number;
  /**
   * Phone framing for the full tier: the scene pulls its camera back so tiles
   * render small. Always false on the fallback tier, which has no scene.
   */
  compact: boolean;
}

/** Full-fat desktop tier body count. */
export const DESKTOP_BODY_COUNT = 72;
/** Constrained (phone / low-end hardware) tier body count. */
export const CONSTRAINED_BODY_COUNT = 40;

/** Hints at or below these read as "low-end"; absent hints read as capable. */
const LOW_END_MAX_CORES = 4;
const LOW_END_MAX_MEMORY_GB = 4;

export function resolveExperienceTier(input: ExperienceTierInput): ExperienceTierResult {
  if (input.prefersReducedMotion || !input.webglSupported) {
    // bodyCount still sizes the DOM fallback grid; maxDpr is moot without GL.
    return { tier: 'fallback', bodyCount: CONSTRAINED_BODY_COUNT, maxDpr: 1, compact: false };
  }
  const lowEnd =
    (input.hardwareConcurrency !== undefined &&
      input.hardwareConcurrency <= LOW_END_MAX_CORES) ||
    (input.deviceMemory !== undefined && input.deviceMemory <= LOW_END_MAX_MEMORY_GB);
  if (input.isMobileViewport) {
    // A phone always gets the constrained roster (the band under the CTAs
    // holds ~40 small tiles), but keeps dpr 2 when it can afford it: at ~40px
    // a tile's logo turns soft below that on a high-density screen.
    return {
      tier: 'full',
      bodyCount: CONSTRAINED_BODY_COUNT,
      maxDpr: lowEnd ? 1.5 : 2,
      compact: true,
    };
  }
  if (lowEnd) {
    return { tier: 'full', bodyCount: CONSTRAINED_BODY_COUNT, maxDpr: 1.5, compact: false };
  }
  return { tier: 'full', bodyCount: DESKTOP_BODY_COUNT, maxDpr: 2, compact: false };
}

export interface FrameloopInput {
  /** Every rapier body is asleep (the Gravity scene's settle signal). */
  allAsleep: boolean;
  /** Hero region intersects the viewport (IntersectionObserver). */
  heroInView: boolean;
  /** document.visibilityState !== 'hidden'. */
  docVisible: boolean;
}

/**
 * The single frameloop rule: render only while there is something to show and
 * someone to show it to. Any reason to idle wins.
 */
export function resolveFrameloop(input: FrameloopInput): 'always' | 'never' {
  return !input.allAsleep && input.heroInView && input.docVisible ? 'always' : 'never';
}
