/**
 * Pure decision tables for the 3D prototypes' degradation ladder and frameloop
 * governor. Every branch lives here (not in the scene JSX) so the full matrix
 * is unit-testable in jsdom without ever touching three.js.
 *
 * Ladder (PLAN.md "Tabs 3+4 — 3D"):
 *   full desktop → full constrained (fewer bodies, lower DPR, no shadows)
 *   → fallback (reduced-motion or no WebGL: DOM-only, scene chunk never loads).
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
}

/** Full-fat desktop tier body count. */
export const DESKTOP_BODY_COUNT = 72;
/** Constrained (mobile viewport / low-end hardware) tier body count. */
export const CONSTRAINED_BODY_COUNT = 40;

/** Hints at or below these read as "low-end"; absent hints read as capable. */
const LOW_END_MAX_CORES = 4;
const LOW_END_MAX_MEMORY_GB = 4;

export function resolveExperienceTier(input: ExperienceTierInput): ExperienceTierResult {
  if (input.prefersReducedMotion || !input.webglSupported) {
    // bodyCount still sizes the DOM fallback grid; maxDpr is moot without GL.
    return { tier: 'fallback', bodyCount: CONSTRAINED_BODY_COUNT, maxDpr: 1 };
  }
  const lowEnd =
    input.isMobileViewport ||
    (input.hardwareConcurrency !== undefined &&
      input.hardwareConcurrency <= LOW_END_MAX_CORES) ||
    (input.deviceMemory !== undefined && input.deviceMemory <= LOW_END_MAX_MEMORY_GB);
  if (lowEnd) {
    return { tier: 'full', bodyCount: CONSTRAINED_BODY_COUNT, maxDpr: 1.5 };
  }
  return { tier: 'full', bodyCount: DESKTOP_BODY_COUNT, maxDpr: 2 };
}

export interface FrameloopInput {
  /** Gravity only: every rapier body is asleep. Drift passes false. */
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
