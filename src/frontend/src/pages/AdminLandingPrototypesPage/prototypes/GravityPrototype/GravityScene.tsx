/**
 * The Gravity physics scene — the ONLY module tree that imports rapier, and it
 * loads exclusively through GravityPrototype's nested React.lazy, so fallback
 * tiers never download it. Kept as thin JSX plumbing: every decision branch
 * lives in the pure modules (spawnPlan, experienceTier, logoRoster).
 */
import { Suspense, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { ContactShadows } from '@react-three/drei';
import {
  BallCollider,
  CuboidCollider,
  Physics,
  RigidBody,
  type RapierRigidBody,
} from '@react-three/rapier';
import { Vector3 } from 'three';
import type { LogoRosterEntry } from '../shared3d/logoRoster';
import { buildSpawnPlan } from './spawnPlan';
import { LogoTileBody, type TileTone } from './LogoTileBody';
import { useSettleGovernor, type SettleGovernor } from './useSettleGovernor';

/**
 * Logo treatment: 'grayscale' holds the monochrome black-on-white aesthetic;
 * flip to 'brand' at review for full-color logos. Nothing else changes.
 */
export const TILE_TONE: TileTone = 'grayscale';

/** Arbitrary, stable seed — the spawn choreography is identical every visit. */
const SPAWN_SEED = 1337;
/** Pointer-repel ball radius (world units). */
const POINTER_BALL_RADIUS = 1.1;
/** Idle frames before handing frameloop control back to the settle governor. */
const POINTER_IDLE_FRAMES = 90;
/** Parking spot for the repel ball before the first real pointer move. */
const BALL_PARK_Y = -50;

const POINTER_FINE_QUERY = '(pointer: fine)';

function subscribePointerFine(onStoreChange: () => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => {};
  const mql = window.matchMedia(POINTER_FINE_QUERY);
  mql.addEventListener('change', onStoreChange);
  return () => mql.removeEventListener('change', onStoreChange);
}

function getPointerFineSnapshot(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(POINTER_FINE_QUERY).matches;
}

function getPointerFineServerSnapshot(): boolean {
  return false;
}

/** Coarse-pointer (touch) devices never mount the repel ball. */
function usePointerFine(): boolean {
  return useSyncExternalStore(
    subscribePointerFine,
    getPointerFineSnapshot,
    getPointerFineServerSnapshot
  );
}

/**
 * Invisible static colliders shaping the pile: floor, side walls sized from
 * the viewport, and front/back walls at z=±0.75 (0.5 thick) that keep the
 * pile shallow. Bare colliders outside a RigidBody are fixed.
 */
function ArenaColliders({ width }: { width: number }) {
  const half = width / 2;
  return (
    <>
      <CuboidCollider args={[half + 2, 0.5, 2]} position={[0, -0.5, 0]} />
      <CuboidCollider args={[0.5, 25, 2]} position={[-(half + 0.5), 24, 0]} />
      <CuboidCollider args={[0.5, 25, 2]} position={[half + 0.5, 24, 0]} />
      <CuboidCollider args={[half + 2, 25, 0.25]} position={[0, 24, 0.75]} />
      <CuboidCollider args={[half + 2, 25, 0.25]} position={[0, 24, -0.75]} />
    </>
  );
}

/**
 * Kinematic ball that shadows the unprojected pointer on the z=0 play plane,
 * shoving tiles aside. DOM pointermove also revives a parked ('never')
 * frameloop via governor.wake(); once the pointer goes idle over a settled
 * pile, frame counting (no timers) hands control back to the governor.
 */
function PointerRepelBall({ governor }: { governor: SettleGovernor }) {
  const bodyRef = useRef<RapierRigidBody>(null);
  const gl = useThree((state) => state.gl);
  const target = useMemo(() => new Vector3(), []);
  const hasPointerRef = useRef(false);
  const idleFramesRef = useRef(0);
  const lastPointerRef = useRef({ x: Number.NaN, y: Number.NaN });

  useEffect(() => {
    const element = gl.domElement;
    const handlePointerMove = () => {
      hasPointerRef.current = true;
      governor.wake();
    };
    element.addEventListener('pointermove', handlePointerMove);
    return () => element.removeEventListener('pointermove', handlePointerMove);
  }, [gl, governor]);

  useFrame((state) => {
    const body = bodyRef.current;
    if (!body) return;
    if (!hasPointerRef.current) {
      body.setNextKinematicTranslation({ x: 0, y: BALL_PARK_Y, z: 0 });
      return;
    }
    const { pointer, camera } = state;
    // Unproject the NDC pointer through the camera onto the z=0 plane.
    target.set(pointer.x, pointer.y, 0.5).unproject(camera).sub(camera.position).normalize();
    const distance = -camera.position.z / target.z;
    target.multiplyScalar(distance).add(camera.position);
    body.setNextKinematicTranslation({ x: target.x, y: target.y, z: 0 });

    if (pointer.x === lastPointerRef.current.x && pointer.y === lastPointerRef.current.y) {
      idleFramesRef.current += 1;
      if (idleFramesRef.current === POINTER_IDLE_FRAMES) governor.refresh();
    } else {
      idleFramesRef.current = 0;
      lastPointerRef.current = { x: pointer.x, y: pointer.y };
    }
  });

  return (
    <RigidBody ref={bodyRef} type="kinematicPosition" colliders={false} ccd>
      <BallCollider args={[POINTER_BALL_RADIUS]} />
    </RigidBody>
  );
}

interface GravitySceneContentProps {
  roster: readonly LogoRosterEntry[];
  showShadows: boolean;
}

function GravitySceneContent({ roster, showShadows }: GravitySceneContentProps) {
  const viewport = useThree((state) => state.viewport);
  // Frozen at mount: resizing must not respawn (teleport) settled bodies.
  const [arenaWidth] = useState(() => Math.min(Math.max(viewport.width, 6), 16));
  const spawnPlan = useMemo(
    () => buildSpawnPlan(roster.length, SPAWN_SEED, arenaWidth),
    [roster.length, arenaWidth]
  );
  const governor = useSettleGovernor(roster.length);
  const pointerFine = usePointerFine();

  return (
    <>
      <ambientLight intensity={0.9} />
      <directionalLight position={[4, 8, 6]} intensity={1.1} />
      <Suspense fallback={null}>
        <Physics timeStep={1 / 60}>
          <ArenaColliders width={arenaWidth} />
          {roster.map((entry, index) => (
            <LogoTileBody
              key={entry.companyId}
              logoUrl={entry.logoUrl}
              position={spawnPlan[index].position}
              rotation={spawnPlan[index].rotation}
              tone={TILE_TONE}
              onSleep={governor.onBodySleep}
              onWake={governor.onBodyWake}
            />
          ))}
          {pointerFine && <PointerRepelBall governor={governor} />}
        </Physics>
      </Suspense>
      {showShadows && (
        <ContactShadows position={[0, 0.02, 0]} opacity={0.3} scale={arenaWidth + 6} blur={2.2} far={2.5} />
      )}
    </>
  );
}

export interface GravitySceneProps {
  roster: readonly LogoRosterEntry[];
  /** Upper bound of the Canvas dpr clamp (from the experience tier). */
  maxDpr: number;
  /** Desktop tier only — mobile/low-end skips contact shadows entirely. */
  showShadows: boolean;
}

export function GravityScene({ roster, maxDpr, showShadows }: GravitySceneProps) {
  return (
    <Canvas dpr={[1, maxDpr]} camera={{ position: [0, 3, 9], fov: 42 }} frameloop="always">
      <GravitySceneContent roster={roster} showShadows={showShadows} />
    </Canvas>
  );
}

export default GravityScene;
