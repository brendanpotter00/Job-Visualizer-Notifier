import { describe, it, expect } from 'vitest';
import {
  buildSpawnPlan,
  dropBaseAboveView,
} from '../../../pages/LandingPage/prototypes/GravityPrototype/spawnPlan';

const SEED = 1337;
const WIDTH = 12;
const BASE = 8;
const TILE_RADIUS = Math.hypot(0.5, 0.5, 0.07);

describe('buildSpawnPlan', () => {
  it('is deterministic for a given (count, seed, width)', () => {
    expect(buildSpawnPlan(72, SEED, WIDTH, BASE)).toEqual(buildSpawnPlan(72, SEED, WIDTH, BASE));
  });

  it('different seeds produce different plans', () => {
    expect(buildSpawnPlan(10, 1, WIDTH, BASE)).not.toEqual(buildSpawnPlan(10, 2, WIDTH, BASE));
  });

  it('produces exactly `count` tiles (and none for zero)', () => {
    expect(buildSpawnPlan(40, SEED, WIDTH, BASE)).toHaveLength(40);
    expect(buildSpawnPlan(0, SEED, WIDTH, BASE)).toHaveLength(0);
  });

  it('staggers drop heights: y strictly increases with index (the ~2.5s rain)', () => {
    const plan = buildSpawnPlan(72, SEED, WIDTH, BASE);
    for (let i = 1; i < plan.length; i += 1) {
      expect(plan[i].position[1]).toBeGreaterThan(plan[i - 1].position[1]);
    }
    expect(plan[0].position[1]).toBeGreaterThan(0);
  });

  it('starts at the drop base, and moving the base moves only y', () => {
    const low = buildSpawnPlan(10, SEED, WIDTH, BASE);
    expect(low[0].position[1]).toBeGreaterThanOrEqual(BASE);
    const high = buildSpawnPlan(10, SEED, WIDTH, BASE + 16);
    for (let i = 0; i < low.length; i += 1) {
      expect(high[i].position[1]).toBeCloseTo(low[i].position[1] + 16);
      expect(high[i].position[0]).toBe(low[i].position[0]);
      expect(high[i].position[2]).toBe(low[i].position[2]);
      expect(high[i].rotation).toEqual(low[i].rotation);
    }
  });

  it('keeps x inside the viewport-derived arena', () => {
    for (const tile of buildSpawnPlan(72, SEED, WIDTH, BASE)) {
      expect(Math.abs(tile.position[0])).toBeLessThanOrEqual(WIDTH / 2);
    }
  });

  it('keeps x sane even for absurdly narrow viewports', () => {
    for (const tile of buildSpawnPlan(20, SEED, 1, BASE)) {
      expect(Math.abs(tile.position[0])).toBeLessThanOrEqual(0.5);
    }
  });

  it('keeps z inside the shallow front/back walls (inner faces at ±0.5)', () => {
    for (const tile of buildSpawnPlan(72, SEED, WIDTH, BASE)) {
      expect(Math.abs(tile.position[2])).toBeLessThanOrEqual(0.5);
    }
  });

  it('bounds the tumble: gentle x/y tilt, full-circle z spin', () => {
    for (const tile of buildSpawnPlan(72, SEED, WIDTH, BASE)) {
      expect(Math.abs(tile.rotation[0])).toBeLessThanOrEqual(0.4);
      expect(Math.abs(tile.rotation[1])).toBeLessThanOrEqual(0.4);
      expect(Math.abs(tile.rotation[2])).toBeLessThanOrEqual(Math.PI);
    }
  });
});

describe('dropBaseAboveView', () => {
  it.each([
    ['desktop hero', 3.45, 10.35, 42],
    ['phone', 9.5, 27.9, 42],
  ])('starts every tile wholly above the top edge of the %s view', (_, cameraY, cameraZ, fov) => {
    const tan = Math.tan((fov * Math.PI) / 360);
    const plan = buildSpawnPlan(72, SEED, WIDTH, dropBaseAboveView(cameraY, cameraZ, fov));
    for (const { position } of plan) {
      const [, y, z] = position;
      const aboveTopEdge = (y + z * tan - (cameraY + cameraZ * tan)) / Math.hypot(1, tan);
      expect(aboveTopEdge).toBeGreaterThan(TILE_RADIUS);
    }
  });
});
