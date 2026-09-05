import { describe, it, expect } from 'vitest';
import {
  ARENA_ESCAPE_Y,
  ARENA_REBUILD_MIN_DELTA,
  ARENA_REBUILD_RATIO,
  ARENA_RESIZE_DEBOUNCE_MS,
  hasEscapedArena,
  MAX_ARENA_WIDTH,
  MIN_ARENA_WIDTH,
  resolveArenaWidth,
  shouldRebuildArena,
} from '../../../pages/LandingPage/prototypes/GravityPrototype/arenaLayout';

describe('resolveArenaWidth', () => {
  it('passes through widths inside the playable range', () => {
    expect(resolveArenaWidth(12.8)).toBe(12.8);
    expect(resolveArenaWidth(MIN_ARENA_WIDTH)).toBe(MIN_ARENA_WIDTH);
    expect(resolveArenaWidth(MAX_ARENA_WIDTH)).toBe(MAX_ARENA_WIDTH);
  });

  it('clamps a phone-narrow viewport up to the minimum (no one-tile tower)', () => {
    // 390x844 measures ~4.65 world units at this camera.
    expect(resolveArenaWidth(4.65)).toBe(MIN_ARENA_WIDTH);
    expect(resolveArenaWidth(0)).toBe(MIN_ARENA_WIDTH);
    expect(resolveArenaWidth(-3)).toBe(MIN_ARENA_WIDTH);
  });

  it('clamps an ultrawide viewport down to the maximum', () => {
    expect(resolveArenaWidth(40)).toBe(MAX_ARENA_WIDTH);
  });

  it('degrades to the minimum rather than NaN when the canvas is unmeasured', () => {
    expect(resolveArenaWidth(Number.NaN)).toBe(MIN_ARENA_WIDTH);
    expect(resolveArenaWidth(Number.POSITIVE_INFINITY)).toBe(MIN_ARENA_WIDTH);
  });
});

describe('shouldRebuildArena', () => {
  it('ignores sub-threshold jitter (scrollbar, font swap, browser chrome)', () => {
    expect(shouldRebuildArena(12.8, 12.8)).toBe(false);
    expect(shouldRebuildArena(12.8, 12.97)).toBe(false);
    expect(shouldRebuildArena(12.8, 12.63)).toBe(false);
  });

  it('fires on a real window resize, in both directions', () => {
    // 1440 -> 900 CSS px is ~12.8 -> ~8 world units.
    expect(shouldRebuildArena(12.8, 8)).toBe(true);
    expect(shouldRebuildArena(8, 12.8)).toBe(true);
    // Desktop -> phone bottoms out at the clamp, still a rebuild.
    expect(shouldRebuildArena(12.8, MIN_ARENA_WIDTH)).toBe(true);
  });

  it('scales the threshold with the current width but never below the floor', () => {
    // Wide arena: the 5% ratio dominates, so the floor alone is NOT enough.
    const ratioThreshold = MAX_ARENA_WIDTH * ARENA_REBUILD_RATIO;
    expect(ratioThreshold).toBeGreaterThan(ARENA_REBUILD_MIN_DELTA);
    expect(shouldRebuildArena(MAX_ARENA_WIDTH, MAX_ARENA_WIDTH - ratioThreshold - 0.01)).toBe(
      true
    );
    expect(
      shouldRebuildArena(MAX_ARENA_WIDTH, MAX_ARENA_WIDTH - ARENA_REBUILD_MIN_DELTA)
    ).toBe(false);

    // Narrow arena: 5% would be 0.3, so the absolute floor takes over.
    expect(MIN_ARENA_WIDTH * ARENA_REBUILD_RATIO).toBeLessThan(ARENA_REBUILD_MIN_DELTA);
    expect(shouldRebuildArena(MIN_ARENA_WIDTH, MIN_ARENA_WIDTH + 0.4)).toBe(false);
    expect(shouldRebuildArena(MIN_ARENA_WIDTH, MIN_ARENA_WIDTH + ARENA_REBUILD_MIN_DELTA)).toBe(
      true
    );
  });

  it('is symmetric in the two widths', () => {
    expect(shouldRebuildArena(10, 11)).toBe(shouldRebuildArena(10, 9));
  });

  it('debounces long enough to coalesce a drag-resize into one rebuild', () => {
    expect(ARENA_RESIZE_DEBOUNCE_MS).toBeGreaterThanOrEqual(300);
    expect(ARENA_RESIZE_DEBOUNCE_MS).toBeLessThanOrEqual(500);
  });
});

describe('hasEscapedArena', () => {
  it('leaves every tile inside the play volume alone', () => {
    // Resting on the floor, mid-drop, and at the top of the spawn stack.
    expect(hasEscapedArena(0)).toBe(false);
    expect(hasEscapedArena(0.5)).toBe(false);
    expect(hasEscapedArena(5)).toBe(false);
    expect(hasEscapedArena(45)).toBe(false);
  });

  it('tolerates a tile briefly sunk into the floor during penetration recovery', () => {
    // Well short of the threshold: a shallow overlap must never trigger a re-drop.
    expect(hasEscapedArena(-0.5)).toBe(false);
    expect(hasEscapedArena(-5)).toBe(false);
    expect(hasEscapedArena(ARENA_ESCAPE_Y + 0.01)).toBe(false);
    // The threshold itself is still in-bounds — strictly below it escapes.
    expect(hasEscapedArena(ARENA_ESCAPE_Y)).toBe(false);
  });

  it('catches a tile that tunnelled out and is now falling forever', () => {
    expect(hasEscapedArena(ARENA_ESCAPE_Y - 0.01)).toBe(true);
    expect(hasEscapedArena(-21)).toBe(true);
    // The measured escape that motivated the guard.
    expect(hasEscapedArena(-2765.09)).toBe(true);
    expect(hasEscapedArena(Number.NEGATIVE_INFINITY)).toBe(true);
  });

  it('treats a blown-up (NaN) position as escaped rather than in-bounds', () => {
    // `NaN < ARENA_ESCAPE_Y` is false, so a naive compare would strand exactly
    // the body that most needs recovering.
    expect(hasEscapedArena(Number.NaN)).toBe(true);
    expect(hasEscapedArena(Number.POSITIVE_INFINITY)).toBe(true);
  });

  it('sits far below the arena floor so it can only mean "tunnelled out"', () => {
    expect(ARENA_ESCAPE_Y).toBeLessThan(-10);
  });
});
