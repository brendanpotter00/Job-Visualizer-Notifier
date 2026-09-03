/**
 * Deterministic spawn choreography for the Gravity pile.
 *
 * Pure function of (count, seed, viewportWidth): tiles get staggered drop
 * heights (index-scaled `y`) so the pile rains in over ~2.5–3s of simulated
 * fall with ZERO timers — physics alone spaces the arrivals. No
 * Date.now()/Math.random() anywhere (react-hooks/purity); jitter comes from
 * mulberry32 so tests can pin exact output.
 */
import { mulberry32 } from '../shared3d/mulberry32';

export interface SpawnTile {
  /** [x, y, z] world units. y grows with index — later tiles start higher. */
  position: [number, number, number];
  /** Initial tumble as an euler [x, y, z] in radians. */
  rotation: [number, number, number];
}

/** Lowest drop height (world units above the floor at y=0). */
const DROP_BASE_Y = 5;
/** Per-index height step — the "stagger" that spaces out arrivals. */
const DROP_STEP_Y = 0.55;
/** Height jitter; strictly < DROP_STEP_Y so `y` stays strictly increasing. */
const DROP_JITTER_Y = 0.4;
/** Keep spawns clear of the side walls (tile half-diagonal ≈ 0.71). */
const WALL_MARGIN = 0.9;
/** Depth jitter; the z walls' inner faces sit at ±0.5, so spawns stay inside. */
const DEPTH_JITTER = 0.3;
/** Gentle x/y tumble; z spins the logo face, so it gets the full circle. */
const TILT_RANGE = 0.4;

export function buildSpawnPlan(
  count: number,
  seed: number,
  viewportWidth: number
): SpawnTile[] {
  const random = mulberry32(seed);
  const halfSpan = Math.max(viewportWidth / 2 - WALL_MARGIN, 0.5);
  const tiles: SpawnTile[] = [];
  for (let i = 0; i < count; i += 1) {
    const x = (random() * 2 - 1) * halfSpan;
    const y = DROP_BASE_Y + i * DROP_STEP_Y + random() * DROP_JITTER_Y;
    const z = (random() * 2 - 1) * DEPTH_JITTER;
    const rotation: [number, number, number] = [
      (random() * 2 - 1) * TILT_RANGE,
      (random() * 2 - 1) * TILT_RANGE,
      (random() * 2 - 1) * Math.PI,
    ];
    tiles.push({ position: [x, y, z], rotation });
  }
  return tiles;
}
