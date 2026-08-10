import { describe, it, expect } from 'vitest';
import {
  ARENA_REBUILD_MIN_DELTA,
  ARENA_REBUILD_RATIO,
  ARENA_RESIZE_DEBOUNCE_MS,
  MAX_ARENA_WIDTH,
  MIN_ARENA_WIDTH,
  resolveArenaWidth,
  shouldRebuildArena,
} from '../../../pages/AdminLandingPrototypesPage/prototypes/GravityPrototype/arenaLayout';

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
