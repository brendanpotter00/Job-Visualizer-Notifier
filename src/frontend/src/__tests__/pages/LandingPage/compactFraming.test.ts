import { describe, it, expect } from 'vitest';
import { resolveCompactFraming } from '../../../pages/LandingPage/prototypes/GravityPrototype/compactFraming';

const FOV = 42;
const TILE_PX = 40;
const INSET_PX = 48;
const tan = Math.tan((FOV * Math.PI) / 360);

/** Where world point (0, y, 0) lands, in CSS px from the canvas top. */
function screenY(worldY: number, cameraY: number, cameraZ: number, heightPx: number) {
  const halfViewHeight = cameraZ * tan;
  return heightPx / 2 - ((worldY - cameraY) / halfViewHeight) * (heightPx / 2);
}

describe('resolveCompactFraming', () => {
  // A 375 × 858 hero is the iPhone-portrait case the pile was dropped for.
  const W = 375;
  const H = 858;

  it('renders one world unit (one tile edge) at exactly tilePx', () => {
    const { cameraPosition } = resolveCompactFraming(W, H, TILE_PX, INSET_PX, FOV);
    const pxPerUnit = H / (2 * cameraPosition[2] * tan);
    expect(pxPerUnit).toBeCloseTo(TILE_PX);
  });

  it('puts the floor (y=0) floorInsetPx above the canvas bottom', () => {
    const { cameraPosition } = resolveCompactFraming(W, H, TILE_PX, INSET_PX, FOV);
    expect(screenY(0, cameraPosition[1], cameraPosition[2], H)).toBeCloseTo(H - INSET_PX);
  });

  it('sizes the arena to the visible width: canvas px / tilePx', () => {
    expect(resolveCompactFraming(W, H, TILE_PX, INSET_PX, FOV).visibleWidth).toBeCloseTo(
      W / TILE_PX
    );
  });

  it('drops tiles from above the top edge, never mid-view', () => {
    const { cameraPosition, dropBaseY } = resolveCompactFraming(W, H, TILE_PX, INSET_PX, FOV);
    expect(screenY(dropBaseY, cameraPosition[1], cameraPosition[2], H)).toBeLessThan(0);
  });

  it('aims level from the centre line (x = 0)', () => {
    expect(resolveCompactFraming(W, H, TILE_PX, INSET_PX, FOV).cameraPosition[0]).toBe(0);
  });

  it('stays finite before the canvas is measured (0 × 0)', () => {
    const framing = resolveCompactFraming(0, 0, TILE_PX, INSET_PX, FOV);
    for (const value of [...framing.cameraPosition, framing.visibleWidth, framing.dropBaseY]) {
      expect(Number.isFinite(value)).toBe(true);
    }
  });
});
