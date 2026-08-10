/**
 * Pure arena-sizing rules for the Gravity pile — the "is this resize worth a
 * re-drop?" decision, extracted so the whole matrix is unit-testable without
 * three/rapier.
 *
 * Why a *rebuild* rather than moving the walls: the side walls are static
 * colliders with settled tiles resting against them. Sliding a wall inward
 * through a sleeping pile makes rapier resolve a deep penetration in one step
 * and ejects the pile across the hero. So the scene never resizes an existing
 * arena — past the threshold it re-spawns the pile at the new width and lets
 * it rain back down (same seed, so the choreography is the familiar one).
 */

/** Narrowest arena (world units). Below this the pile stacks into a tower. */
export const MIN_ARENA_WIDTH = 6;
/** Widest arena (world units). Beyond this the pile spreads one tile thin. */
export const MAX_ARENA_WIDTH = 16;

/**
 * Absolute floor on "significant" (world units). Guards the narrow end, where
 * a percentage alone would fire on a few px of scrollbar.
 */
export const ARENA_REBUILD_MIN_DELTA = 0.5;
/** Relative significance — 5% of the current arena width. */
export const ARENA_REBUILD_RATIO = 0.05;
/**
 * Trailing debounce for the size stream (ms). Long enough that a drag-resize
 * or an orientation change settles into ONE rebuild; short enough that the
 * re-drop reads as a response to the resize rather than a random event.
 */
export const ARENA_RESIZE_DEBOUNCE_MS = 350;

/** Clamps the live R3F viewport width into the playable arena range. */
export function resolveArenaWidth(viewportWidth: number): number {
  if (!Number.isFinite(viewportWidth)) return MIN_ARENA_WIDTH;
  return Math.min(Math.max(viewportWidth, MIN_ARENA_WIDTH), MAX_ARENA_WIDTH);
}

/**
 * True when `next` differs from `current` enough to justify throwing the pile
 * away and re-dropping it. Deliberately hysteretic: font-swap reflows, a
 * scrollbar appearing, and browser-chrome jitter all land well under the
 * threshold and leave the settled pile alone.
 */
export function shouldRebuildArena(current: number, next: number): boolean {
  const threshold = Math.max(
    ARENA_REBUILD_MIN_DELTA,
    Math.abs(current) * ARENA_REBUILD_RATIO
  );
  return Math.abs(next - current) >= threshold;
}
