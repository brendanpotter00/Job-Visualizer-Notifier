/**
 * The Gravity physics scene — the ONLY module tree that imports rapier, and it
 * loads exclusively through GravityPrototype's nested React.lazy, so fallback
 * tiers never download it. Kept as thin JSX plumbing: every decision branch
 * lives in the pure modules (spawnPlan, arenaLayout, pointerInput,
 * experienceTier, logoRoster).
 */
import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import {
  BallCollider,
  CuboidCollider,
  Physics,
  RigidBody,
  type RapierRigidBody,
} from '@react-three/rapier';
import { Vector3 } from 'three';
import type { LogoRosterEntry } from '../shared3d/logoRoster';
import {
  ARENA_RESIZE_DEBOUNCE_MS,
  resolveArenaWidth,
  shouldRebuildArena,
} from './arenaLayout';
import { HERO_TOUCH_ACTION, shouldRetractOnRelease, toNdcPointer } from './pointerInput';
import { buildSpawnPlan } from './spawnPlan';
import { LogoTileBody, type TileTone } from './LogoTileBody';
import { useSettleGovernor, type SettleGovernor } from './useSettleGovernor';

/**
 * Logo treatment: 'brand' renders full-color logos (review feedback 2026-08-09
 * — the tiles are the one deliberate splash of color on the monochrome page);
 * 'grayscale' remains available to flip back.
 */
export const TILE_TONE: TileTone = 'brand';

/** Arbitrary, stable seed — the spawn choreography is identical every visit. */
const SPAWN_SEED = 1337;
/** Pointer-repel ball radius (world units). */
const POINTER_BALL_RADIUS = 1.1;
/**
 * Idle frames (~1.5s at 60Hz) before the repel ball retracts and hands
 * frameloop control back to the settle governor. Frames, not timers — a parked
 * frameloop runs neither.
 */
const POINTER_IDLE_FRAMES = 90;
/** Off-camera parking spot for the repel ball whenever the pointer is idle. */
const BALL_PARK_Y = -50;
/**
 * Pointer jumps beyond this (world units) are treated as discontinuities —
 * see PointerRepelBall. ~3 units is ≈340 CSS px at this camera, i.e. 20 000
 * px/s at 60Hz: no hand produces that, so ordinary motion never trips it.
 */
const BALL_TELEPORT_DISTANCE = 3;

/**
 * Invisible static colliders shaping the pile: floor, side walls sized from
 * the viewport, and front/back walls that keep the pile shallow. Bare
 * colliders outside a RigidBody are fixed.
 *
 * Every wall is deliberately THICK, with its inner face on the play-volume
 * boundary (floor top y=0, sides x=±half, front/back z=±0.5). Tiles carry no
 * CCD, so the only thing standing between a hard shove and a tile tunnelling
 * out of the arena is how far a single 1/60s step can carry it — 4 world units
 * of wall is far more than any velocity the scene can produce. Thickness is
 * free: static colliders, unchanged count, no extra broad-phase pairs of note.
 */
const WALL_THICKNESS = 2;

function ArenaColliders({ width }: { width: number }) {
  const half = width / 2;
  return (
    <>
      <CuboidCollider
        args={[half + 2, WALL_THICKNESS, 2]}
        position={[0, -WALL_THICKNESS, 0]}
      />
      <CuboidCollider
        args={[WALL_THICKNESS, 25, 2]}
        position={[-(half + WALL_THICKNESS), 24, 0]}
      />
      <CuboidCollider
        args={[WALL_THICKNESS, 25, 2]}
        position={[half + WALL_THICKNESS, 24, 0]}
      />
      <CuboidCollider
        args={[half + 2, 25, WALL_THICKNESS]}
        position={[0, 24, 0.5 + WALL_THICKNESS]}
      />
      <CuboidCollider
        args={[half + 2, 25, WALL_THICKNESS]}
        position={[0, 24, -(0.5 + WALL_THICKNESS)]}
      />
    </>
  );
}

/**
 * Kinematic ball that shadows the pointer on the z=0 play plane, shoving tiles
 * aside — mouse, finger, or stylus alike. DOM pointer events also revive a
 * parked ('never') frameloop via governor.wake(); once a hovering pointer goes
 * idle over a settled pile, frame counting (no timers) hands control back to
 * the governor.
 *
 * Touch: `pointerdown` (not just `pointermove`) starts the tracking, because a
 * finger has no position until it lands — the first frame after touchdown
 * takes the teleport path below and drops the ball onto the finger with no
 * implied velocity, so tapping the pile never flings it. Lifting the finger
 * retracts the ball immediately (`shouldRetractOnRelease`): touch has no
 * hover, so the alternative is a ghost ball wedged in the pile keeping it
 * awake for 90 frames. Coordinates come from these events rather than R3F's
 * shared `state.pointer` for the same reason — it has no meaningful value
 * between touch gestures.
 *
 * Motion vs teleport: rapier derives a kinematic body's velocity from
 * `setNextKinematicTranslation` — position delta over the step. That is what
 * makes the ball shove tiles, but it also means any *discontinuous* jump reads
 * as an enormous velocity. The ball starts parked at y=-50 (off-camera, so it
 * can't disturb the drop), so the user's very first pointer move used to
 * request a 50-unit jump in one 1/60s step: ~3000 units/s, a CCD sweep straight
 * up through the settled pile that launched tiles hundreds of units into the
 * air and cost a ~100ms frame. Anything past BALL_TELEPORT_DISTANCE is
 * therefore a hard `setTranslation` (position only, no implied velocity); real
 * pointer motion stays on the velocity path and keeps tracking the cursor 1:1.
 *
 * Idle retract: a kinematic body is never asleep, and the tiles touching it
 * cannot fall asleep either. A cursor simply left sitting in the pile — the
 * normal end state after playing with the logos — therefore pinned the sleep
 * counter below `bodyCount` forever and the governor could never park the
 * frameloop: measured 186ms/s of CPU burning indefinitely. After
 * POINTER_IDLE_FRAMES with no pointer movement the ball retracts to its
 * parking spot (a `setTranslation`, so no shove on the way out), the pile
 * settles, and the loop parks. The next pointer move re-places it through the
 * teleport path above.
 */
function PointerRepelBall({ governor }: { governor: SettleGovernor }) {
  const bodyRef = useRef<RapierRigidBody>(null);
  const gl = useThree((state) => state.gl);
  const width = useThree((state) => state.size.width);
  const height = useThree((state) => state.size.height);
  const target = useMemo(() => new Vector3(), []);
  // Reused every frame: rapier only reads these fields, so one mutable object
  // keeps the per-frame tracking path allocation-free. A ref, not a useMemo —
  // this object is written every frame, which is exactly what a ref is for.
  // The retract paths below keep their own literal: they fire once per
  // gesture, not per frame.
  const nextTranslationRef = useRef({ x: 0, y: 0, z: 0 });
  const trackingRef = useRef(false);
  const idleFramesRef = useRef(0);
  const pointerRef = useRef({ x: 0, y: 0 });
  const lastPointerRef = useRef({ x: Number.NaN, y: Number.NaN });

  useEffect(() => {
    const element = gl.domElement;
    const retract = () => {
      trackingRef.current = false;
      idleFramesRef.current = 0;
      lastPointerRef.current.x = Number.NaN;
      lastPointerRef.current.y = Number.NaN;
      // Position only (no implied velocity): the ball must not shove on its
      // way out. The next contact re-places it through the teleport path.
      bodyRef.current?.setTranslation({ x: 0, y: BALL_PARK_Y, z: 0 }, true);
      governor.refresh();
    };
    const handleTrack = (event: PointerEvent) => {
      const ndc = toNdcPointer(event.offsetX, event.offsetY, width, height);
      pointerRef.current.x = ndc.x;
      pointerRef.current.y = ndc.y;
      trackingRef.current = true;
      governor.wake();
    };
    const handleRelease = (event: PointerEvent) => {
      if (shouldRetractOnRelease(event.pointerType)) retract();
    };
    element.addEventListener('pointerdown', handleTrack);
    element.addEventListener('pointermove', handleTrack);
    element.addEventListener('pointerup', handleRelease);
    element.addEventListener('pointercancel', handleRelease);
    return () => {
      element.removeEventListener('pointerdown', handleTrack);
      element.removeEventListener('pointermove', handleTrack);
      element.removeEventListener('pointerup', handleRelease);
      element.removeEventListener('pointercancel', handleRelease);
    };
  }, [gl, governor, width, height]);

  useFrame((state) => {
    const body = bodyRef.current;
    // Between gestures (and before the first one) the ball stays parked.
    if (!body || !trackingRef.current) return;

    const pointer = pointerRef.current;
    const { camera } = state;
    if (pointer.x === lastPointerRef.current.x && pointer.y === lastPointerRef.current.y) {
      idleFramesRef.current += 1;
      if (idleFramesRef.current === POINTER_IDLE_FRAMES) {
        body.setTranslation({ x: 0, y: BALL_PARK_Y, z: 0 }, true);
        governor.refresh();
      }
      // Stay retracted until the pointer actually moves again.
      if (idleFramesRef.current >= POINTER_IDLE_FRAMES) return;
    } else {
      idleFramesRef.current = 0;
      lastPointerRef.current.x = pointer.x;
      lastPointerRef.current.y = pointer.y;
    }

    // Unproject the NDC pointer through the camera onto the z=0 plane.
    target.set(pointer.x, pointer.y, 0.5).unproject(camera).sub(camera.position).normalize();
    const distance = -camera.position.z / target.z;
    target.multiplyScalar(distance).add(camera.position);

    const current = body.translation();
    const jumped =
      Math.abs(target.x - current.x) > BALL_TELEPORT_DISTANCE ||
      Math.abs(target.y - current.y) > BALL_TELEPORT_DISTANCE ||
      Math.abs(current.z) > BALL_TELEPORT_DISTANCE;
    const next = nextTranslationRef.current;
    next.x = target.x;
    next.y = target.y;
    next.z = 0;
    if (jumped) body.setTranslation(next, true);
    else body.setNextKinematicTranslation(next);
  });

  return (
    <RigidBody
      ref={bodyRef}
      type="kinematicPosition"
      position={[0, BALL_PARK_Y, 0]}
      colliders={false}
      ccd
    >
      <BallCollider args={[POINTER_BALL_RADIUS]} />
    </RigidBody>
  );
}

/**
 * One pile: the arena walls, the tile bodies, the repel ball, and the settle
 * governor that counts them. Everything stateful about a given arena width
 * lives in here, so remounting this component (via the `arena.generation` key
 * below) is a complete, honest reset — the governor's sleep tally, the frameloop
 * re-arm, and the pointer bookkeeping all start from scratch rather than
 * inheriting the previous pile's counters. rapier's `Physics` world stays
 * mounted above it; only the bodies are replaced.
 */
function GravityPile({
  roster,
  arenaWidth,
}: {
  roster: readonly LogoRosterEntry[];
  arenaWidth: number;
}) {
  const spawnPlan = useMemo(
    () => buildSpawnPlan(roster.length, SPAWN_SEED, arenaWidth),
    [roster.length, arenaWidth]
  );
  const governor = useSettleGovernor(roster.length);

  return (
    <>
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
      <PointerRepelBall governor={governor} />
    </>
  );
}

interface GravitySceneContentProps {
  roster: readonly LogoRosterEntry[];
}

function GravitySceneContent({ roster }: GravitySceneContentProps) {
  // Reactive: R3F recomputes `viewport` from the measured canvas on every
  // resize / orientation change, so this is the live arena target.
  const viewportWidth = useThree((state) => state.viewport.width);
  const [arena, setArena] = useState(() => ({
    width: resolveArenaWidth(viewportWidth),
    generation: 0,
  }));

  /**
   * Resize → re-drop. The arena width is NOT bound straight to the viewport:
   * dragging static walls through a settled pile ejects it (see arenaLayout).
   * Instead a significant, settled-down size change bumps `generation`, which
   * remounts the pile so the tiles rain into the new width — a deliberate
   * re-drop instead of a wall squeeze. Sub-threshold jitter (scrollbar, font
   * swap, browser chrome) leaves the pile alone, and a resize that returns to
   * where it started inside the debounce window cancels itself: the effect
   * re-runs, finds nothing significant, and the cleanup already dropped the
   * pending timer.
   */
  useEffect(() => {
    const next = resolveArenaWidth(viewportWidth);
    if (!shouldRebuildArena(arena.width, next)) return undefined;
    const timer = window.setTimeout(() => {
      setArena((prev) => ({ width: next, generation: prev.generation + 1 }));
    }, ARENA_RESIZE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [viewportWidth, arena.width]);

  return (
    <>
      <ambientLight intensity={0.9} />
      <directionalLight position={[4, 8, 6]} intensity={1.1} />
      <Suspense fallback={null}>
        <Physics timeStep={1 / 60}>
          <GravityPile key={arena.generation} roster={roster} arenaWidth={arena.width} />
        </Physics>
      </Suspense>
    </>
  );
}

export interface GravitySceneProps {
  roster: readonly LogoRosterEntry[];
  /** Upper bound of the Canvas dpr clamp (from the experience tier). */
  maxDpr: number;
}

/**
 * Camera. The explicit `rotation` matters: without it R3F helpfully aims the
 * camera at the origin, which puts the floor plane (y=0) dead centre — the
 * pile settled across the middle of the hero, on top of the headline, leaving
 * the reserved lower half empty. Aiming level instead drops the floor line to
 * ~93% of the canvas height, so the pile fills the reserved band at the bottom
 * of the hero and the copy sits over clean space above it.
 */
const CAMERA = { position: [0, 3, 9] as const, rotation: [0, 0, 0] as const, fov: 42 };

/**
 * `touch-action` goes on R3F's wrapper div (it owns the only style hook the
 * Canvas exposes; the inner <canvas> inherits the restriction because the
 * effective touch-action of a gesture is the intersection down the ancestor
 * chain). See HERO_TOUCH_ACTION for why `pan-y pinch-zoom`.
 */
const CANVAS_STYLE = { touchAction: HERO_TOUCH_ACTION } as const;

export function GravityScene({ roster, maxDpr }: GravitySceneProps) {
  return (
    <Canvas dpr={[1, maxDpr]} camera={CAMERA} frameloop="always" style={CANVAS_STYLE}>
      <GravitySceneContent roster={roster} />
    </Canvas>
  );
}

export default GravityScene;
