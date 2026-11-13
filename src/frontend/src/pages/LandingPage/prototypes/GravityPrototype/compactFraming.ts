/**
 * Phone framing for the Gravity pile — pure, so the whole rule is unit-testable
 * without three/rapier.
 *
 * Why phones need their own camera: the desktop camera is fixed (z=9, fov 42),
 * so a tile is always ~1/7 of the canvas HEIGHT. On a 375px-wide phone that is
 * a ~124px tile in a ~3-unit-wide view, the arena floor clamps to
 * MIN_ARENA_WIDTH (wider than the screen), and the pile stacks seven tiles
 * high over the copy. That is why phones used to get the static grid instead.
 *
 * The fix pulls the camera back until one world unit (one tile edge) is
 * `tilePx` CSS px. Nothing about the physics changes — tile size, gravity,
 * walls and the pointer ball all stay in world units — the pile is simply
 * viewed from further away, so it reads at the same scale as the static grid
 * and settles a few tiles high in the band under the CTAs.
 */

/** Spawn this far (world units) above the top of the view, clear of a tile's ~0.71 half-diagonal. */
const SPAWN_CLEARANCE = 1;

export interface CompactFraming {
  /** Camera position, aimed level (rotation 0) like the desktop camera. */
  cameraPosition: [number, number, number];
  /** World-unit width visible on the z=0 play plane — the live arena target. */
  visibleWidth: number;
  /**
   * Lowest drop height (world units). Just above the top of the view, so
   * tiles fall in from the top edge rather than appearing mid-air: the phone
   * view is ~20 units tall, far above the desktop spawn base of 5.
   */
  dropBaseY: number;
}

/**
 * @param widthPx    canvas width (CSS px)
 * @param heightPx   canvas height (CSS px)
 * @param tilePx     on-screen edge of one tile (CSS px)
 * @param floorInsetPx distance from the canvas bottom up to the floor (CSS px)
 * @param fovDeg     the camera's vertical field of view (degrees)
 */
export function resolveCompactFraming(
  widthPx: number,
  heightPx: number,
  tilePx: number,
  floorInsetPx: number,
  fovDeg: number
): CompactFraming {
  // Before the canvas is measured (or in a degenerate layout) fall back to a
  // 1px canvas rather than dividing by zero; R3F re-renders once it measures.
  const width = Number.isFinite(widthPx) && widthPx > 0 ? widthPx : 1;
  const height = Number.isFinite(heightPx) && heightPx > 0 ? heightPx : 1;
  const halfFovTan = Math.tan((fovDeg * Math.PI) / 360);

  // Visible half-height at z=0 is z·tan(fov/2); setting it to (height/2)/tilePx
  // makes one world unit exactly tilePx CSS px.
  const halfViewHeight = height / 2 / tilePx;
  const z = halfViewHeight / halfFovTan;
  // Aimed level, so the floor (y=0) sits `cameraY` units below the centre;
  // put it `floorInsetPx` above the canvas bottom.
  const cameraY = Math.max(halfViewHeight - floorInsetPx / tilePx, 0);

  return {
    cameraPosition: [0, cameraY, z],
    visibleWidth: width / tilePx,
    dropBaseY: cameraY + halfViewHeight + SPAWN_CLEARANCE,
  };
}
