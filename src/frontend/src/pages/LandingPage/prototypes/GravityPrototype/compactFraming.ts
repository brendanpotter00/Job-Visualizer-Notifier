const SPAWN_CLEARANCE = 1;

export interface CompactFraming {
  cameraPosition: [number, number, number];
  visibleWidth: number;
  dropBaseY: number;
}

export function resolveCompactFraming(
  widthPx: number,
  heightPx: number,
  tilePx: number,
  floorInsetPx: number,
  fovDeg: number
): CompactFraming {
  const width = Number.isFinite(widthPx) && widthPx > 0 ? widthPx : 1;
  const height = Number.isFinite(heightPx) && heightPx > 0 ? heightPx : 1;
  const halfFovTan = Math.tan((fovDeg * Math.PI) / 360);

  const halfViewHeight = height / 2 / tilePx;
  const z = halfViewHeight / halfFovTan;
  const cameraY = Math.max(halfViewHeight - floorInsetPx / tilePx, 0);

  return {
    cameraPosition: [0, cameraY, z],
    visibleWidth: width / tilePx,
    dropBaseY: cameraY + halfViewHeight + SPAWN_CLEARANCE,
  };
}
