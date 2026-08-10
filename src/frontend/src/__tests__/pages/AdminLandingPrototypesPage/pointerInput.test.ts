import { describe, it, expect } from 'vitest';
import {
  HERO_TOUCH_ACTION,
  shouldRetractOnRelease,
  toNdcPointer,
} from '../../../pages/AdminLandingPrototypesPage/prototypes/GravityPrototype/pointerInput';

describe('toNdcPointer', () => {
  const W = 400;
  const H = 200;

  it('maps the canvas centre to the NDC origin', () => {
    expect(toNdcPointer(W / 2, H / 2, W, H)).toEqual({ x: 0, y: 0 });
  });

  it('maps the corners to the NDC unit square (y flipped)', () => {
    expect(toNdcPointer(0, 0, W, H)).toEqual({ x: -1, y: 1 });
    expect(toNdcPointer(W, H, W, H)).toEqual({ x: 1, y: -1 });
    expect(toNdcPointer(0, H, W, H)).toEqual({ x: -1, y: -1 });
    expect(toNdcPointer(W, 0, W, H)).toEqual({ x: 1, y: 1 });
  });

  it('is linear across the canvas', () => {
    expect(toNdcPointer(W * 0.25, H * 0.75, W, H)).toEqual({ x: -0.5, y: -0.5 });
  });

  it('keeps going past the edges — a captured touch drag leaves the canvas', () => {
    expect(toNdcPointer(-W / 2, H / 2, W, H)).toEqual({ x: -2, y: 0 });
    expect(toNdcPointer(W * 1.5, H / 2, W, H)).toEqual({ x: 2, y: 0 });
  });

  it('degrades to the origin instead of NaN/Infinity on an unmeasured canvas', () => {
    expect(toNdcPointer(10, 10, 0, 0)).toEqual({ x: 0, y: 0 });
    expect(toNdcPointer(10, 10, W, 0)).toEqual({ x: 0, y: 0 });
    expect(toNdcPointer(10, 10, Number.NaN, H)).toEqual({ x: 0, y: 0 });
  });
});

describe('shouldRetractOnRelease', () => {
  it('keeps the ball under a mouse cursor after a click (hover persists)', () => {
    expect(shouldRetractOnRelease('mouse')).toBe(false);
  });

  it('retracts the moment a finger or stylus lifts (no hover exists)', () => {
    expect(shouldRetractOnRelease('touch')).toBe(true);
    expect(shouldRetractOnRelease('pen')).toBe(true);
  });

  it('retracts for an unknown/empty pointerType rather than stranding the ball', () => {
    expect(shouldRetractOnRelease('')).toBe(true);
  });
});

describe('HERO_TOUCH_ACTION', () => {
  it('lets the page scroll vertically under the hero canvas', () => {
    expect(HERO_TOUCH_ACTION).toContain('pan-y');
  });

  it('keeps the page pinch-zoomable', () => {
    expect(HERO_TOUCH_ACTION).toContain('pinch-zoom');
  });

  it('claims horizontal drags for the scene (no pan-x)', () => {
    expect(HERO_TOUCH_ACTION).not.toContain('pan-x');
    expect(HERO_TOUCH_ACTION).not.toBe('auto');
    expect(HERO_TOUCH_ACTION).not.toBe('none');
  });
});
