import { useEffect, useMemo, useRef } from 'react';
import { useTexture } from '@react-three/drei';
import {
  RigidBody,
  useAfterPhysicsStep,
  type RapierRigidBody,
} from '@react-three/rapier';
import { BoxGeometry, MeshLambertMaterial, SRGBColorSpace, type Texture } from 'three';
import { hasEscapedArena } from './arenaLayout';

export type TileTone = 'grayscale' | 'brand';

/**
 * Reused for both velocity resets on the respawn path below — rapier reads the
 * fields and keeps nothing, so one module-scope literal serves every tile.
 */
const ZERO_VELOCITY = { x: 0, y: 0, z: 0 } as const;

/**
 * Shared across every tile — one geometry and one edge material for the whole
 * pile. Module-scope is safe: this module only ever loads inside the lazy
 * Gravity scene chunk, and the singletons live for the lifetime of the scene.
 */
const TILE_GEOMETRY = new BoxGeometry(1, 1, 0.14);
const EDGE_MATERIAL = new MeshLambertMaterial({ color: '#d9d9d9' });

/** Material-array slots the merged groups below address. */
const EDGE_MATERIAL_SLOT = 0;
const FACE_MATERIAL_SLOT = 1;

/**
 * Six groups down to two — the single cheapest draw-call cut in the scene.
 *
 * three renders one draw call per geometry *group*, never merging adjacent
 * groups even when they resolve to the identical material instance. A stock
 * BoxGeometry emits one group per face, so each tile cost SIX calls (four of
 * them the same EDGE_MATERIAL) and the 72-tile pile measured 432 draw calls a
 * frame. BoxGeometry builds its faces in +x, -x, +y, -y, +z, -z order and
 * appends each one's indices in that same order, so the four edge faces are a
 * single contiguous run: collapsing them into one group leaves the vertex data
 * (and therefore the cuboid collider derived from it) untouched and renders a
 * pixel-identical tile in two calls — 432 -> 144 for the pile.
 *
 * Counts are summed from the real groups rather than hard-coded, so a future
 * segmented box still splits at the right index.
 */
function mergeEdgeGroups(geometry: BoxGeometry): void {
  const edgeIndexCount = geometry.groups
    .slice(0, 4)
    .reduce((total, group) => total + group.count, 0);
  const faceIndexCount = geometry.groups
    .slice(4)
    .reduce((total, group) => total + group.count, 0);
  geometry.clearGroups();
  geometry.addGroup(0, edgeIndexCount, EDGE_MATERIAL_SLOT);
  geometry.addGroup(edgeIndexCount, faceIndexCount, FACE_MATERIAL_SLOT);
}

mergeEdgeGroups(TILE_GEOMETRY);

/**
 * Cheapest possible grayscale: rewrite the sampled map color to its Rec. 709
 * luminance in the fragment shader. No canvas pre-processing, no extra
 * textures — one string splice at compile time. All grayscale tiles share one
 * GL program via the explicit cache key.
 */
function applyGrayscale(material: MeshLambertMaterial): void {
  material.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <map_fragment>',
      [
        '#include <map_fragment>',
        'diffuseColor.rgb = vec3(dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722)));',
      ].join('\n')
    );
  };
  material.customProgramCacheKey = () => 'logo-tile-grayscale';
}

function applySrgb(texture: Texture | Texture[]): void {
  for (const item of Array.isArray(texture) ? texture : [texture]) {
    item.colorSpace = SRGBColorSpace;
  }
}

interface LogoTileBodyProps {
  logoUrl: string;
  position: [number, number, number];
  rotation: [number, number, number];
  tone: TileTone;
  onSleep: () => void;
  onWake: () => void;
}

/**
 * One physical logo tile: a rapier RigidBody around a box mesh whose ±z faces
 * carry the company logo and whose four edges share EDGE_MATERIAL — two
 * geometry groups, two draw calls (see mergeEdgeGroups). Suspends via
 * useTexture until the logo PNG arrives.
 *
 * Deliberately NO `ccd`: continuous collision detection sweeps every enabled
 * body against the whole broad-phase each substep, and with ~72 of them in a
 * dense pile it measured 1.74ms per 1/60s step — 4x the 0.44ms the same step
 * costs without it, and the single largest CPU cost while the pointer stirs
 * the pile. These tiles fall a few units under gravity and are shoved by a
 * speed-bounded pointer ball, so per-step travel stays far below the 4-unit
 * arena walls (see ArenaColliders) and discrete detection never misses.
 */
export function LogoTileBody({
  logoUrl,
  position,
  rotation,
  tone,
  onSleep,
  onWake,
}: LogoTileBodyProps) {
  const texture = useTexture(logoUrl, applySrgb);

  const faceMaterial = useMemo(() => {
    const material = new MeshLambertMaterial({ map: texture });
    if (tone === 'grayscale') applyGrayscale(material);
    return material;
  }, [texture, tone]);

  useEffect(() => () => faceMaterial.dispose(), [faceMaterial]);

  // Two slots, matching the two merged geometry groups (see mergeEdgeGroups).
  const materials = useMemo(() => [EDGE_MATERIAL, faceMaterial], [faceMaterial]);

  const bodyRef = useRef<RapierRigidBody>(null);

  /**
   * Escape guard. A tile can still be shoved through a wall — the pointer ball
   * teleports (see BALL_TELEPORT_DISTANCE) and landing it inside a settled pile
   * makes rapier resolve the penetration explosively — and without CCD nothing
   * stops the ejected tile. Once out it falls forever, never sleeps, and so pins
   * the settle governor's tally one short of `bodyCount`: the frameloop can
   * never park and the hero burns 60fps for the rest of the session. That is
   * the defect this guard closes; it is a frameloop fix, not a physics tweak.
   *
   * The recovery is a re-drop at this tile's own seeded spawn point (`position`
   * — pure, from buildSpawnPlan, identical every visit), with both velocities
   * zeroed so a tile that had accelerated to terminal velocity does not re-enter
   * the arena as a projectile and eject its neighbours. Sleep bookkeeping needs
   * no special handling and must not get any: an escapee is awake by definition
   * (it is falling), so it is already absent from the governor's asleep tally,
   * `setTranslation(..., true)` on an awake body fires no wake event, and the
   * tile is counted again the ordinary way when it lands and sleeps.
   *
   * Per physics step, not per rendered frame, and rapier does not step while the
   * frameloop is parked — so a settled scene pays nothing at all for this.
   */
  useAfterPhysicsStep(() => {
    const body = bodyRef.current;
    if (!body || !hasEscapedArena(body.translation().y)) return;
    body.setLinvel(ZERO_VELOCITY, false);
    body.setAngvel(ZERO_VELOCITY, false);
    body.setTranslation({ x: position[0], y: position[1], z: position[2] }, true);
  });

  return (
    <RigidBody
      ref={bodyRef}
      colliders="cuboid"
      position={position}
      rotation={rotation}
      linearDamping={0.15}
      restitution={0.2}
      friction={0.8}
      onSleep={onSleep}
      onWake={onWake}
    >
      <mesh geometry={TILE_GEOMETRY} material={materials} />
    </RigidBody>
  );
}
