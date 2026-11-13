import { describe, it, expect } from 'vitest';
import {
  buildSpawnPlan,
  DEFAULT_DROP_BASE_Y,
} from '../../../pages/LandingPage/prototypes/GravityPrototype/spawnPlan';

const SEED = 1337;
const WIDTH = 12;

describe('buildSpawnPlan', () => {
  it('is deterministic for a given (count, seed, width)', () => {
    expect(buildSpawnPlan(72, SEED, WIDTH)).toEqual(buildSpawnPlan(72, SEED, WIDTH));
  });

  it('different seeds produce different plans', () => {
    expect(buildSpawnPlan(10, 1, WIDTH)).not.toEqual(buildSpawnPlan(10, 2, WIDTH));
  });

  it('produces exactly `count` tiles (and none for zero)', () => {
    expect(buildSpawnPlan(40, SEED, WIDTH)).toHaveLength(40);
    expect(buildSpawnPlan(0, SEED, WIDTH)).toHaveLength(0);
  });

  it('staggers drop heights: y strictly increases with index (the ~2.5s rain)', () => {
    const plan = buildSpawnPlan(72, SEED, WIDTH);
    for (let i = 1; i < plan.length; i += 1) {
      expect(plan[i].position[1]).toBeGreaterThan(plan[i - 1].position[1]);
    }
    expect(plan[0].position[1]).toBeGreaterThan(0);
  });

  it('defaults the drop base to the desktop view and honours an explicit one', () => {
    const desktop = buildSpawnPlan(10, SEED, WIDTH);
    expect(desktop[0].position[1]).toBeGreaterThanOrEqual(DEFAULT_DROP_BASE_Y);
    // Phones drop from above their much taller view (see compactFraming): the
    // whole plan shifts up by the difference, x/z/tumble unchanged.
    const phone = buildSpawnPlan(10, SEED, WIDTH, DEFAULT_DROP_BASE_Y + 16);
    for (let i = 0; i < desktop.length; i += 1) {
      expect(phone[i].position[1]).toBeCloseTo(desktop[i].position[1] + 16);
      expect(phone[i].position[0]).toBe(desktop[i].position[0]);
      expect(phone[i].position[2]).toBe(desktop[i].position[2]);
      expect(phone[i].rotation).toEqual(desktop[i].rotation);
    }
  });

  it('keeps x inside the viewport-derived arena', () => {
    for (const tile of buildSpawnPlan(72, SEED, WIDTH)) {
      expect(Math.abs(tile.position[0])).toBeLessThanOrEqual(WIDTH / 2);
    }
  });

  it('keeps x sane even for absurdly narrow viewports', () => {
    for (const tile of buildSpawnPlan(20, SEED, 1)) {
      expect(Math.abs(tile.position[0])).toBeLessThanOrEqual(0.5);
    }
  });

  it('keeps z inside the shallow front/back walls (inner faces at ±0.5)', () => {
    for (const tile of buildSpawnPlan(72, SEED, WIDTH)) {
      expect(Math.abs(tile.position[2])).toBeLessThanOrEqual(0.5);
    }
  });

  it('bounds the tumble: gentle x/y tilt, full-circle z spin', () => {
    for (const tile of buildSpawnPlan(72, SEED, WIDTH)) {
      expect(Math.abs(tile.rotation[0])).toBeLessThanOrEqual(0.4);
      expect(Math.abs(tile.rotation[1])).toBeLessThanOrEqual(0.4);
      expect(Math.abs(tile.rotation[2])).toBeLessThanOrEqual(Math.PI);
    }
  });
});
