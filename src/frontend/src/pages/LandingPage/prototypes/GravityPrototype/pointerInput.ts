/**
 * Pure pointer plumbing for the Gravity repel ball. The scene drives the ball
 * from its OWN DOM pointer events rather than R3F's `state.pointer`, because
 * `state.pointer` is only meaningful for a device that hovers: on touch there
 * is no pointer between gestures, so the shared value goes stale the moment
 * the finger lifts and the ball would keep sitting in the pile. Everything
 * decidable without a browser lives here.
 */

export interface NdcPoint {
  /** Normalised device coordinate, -1 (left) … 1 (right). */
  x: number;
  /** Normalised device coordinate, -1 (bottom) … 1 (top). */
  y: number;
}

/**
 * Canvas-relative pixel offsets → NDC, matching R3F's own default `compute`
 * (`event.offsetX / size.width`). Using offsets + the already-measured canvas
 * size keeps this off the layout path — no `getBoundingClientRect()` per move.
 *
 * Values outside [-1, 1] are legitimate and preserved: a touch drag keeps
 * implicit pointer capture after the finger leaves the canvas, and the ball
 * should follow it out of frame rather than clamp to the edge.
 */
export function toNdcPointer(
  offsetX: number,
  offsetY: number,
  width: number,
  height: number
): NdcPoint {
  if (!(width > 0) || !(height > 0)) return { x: 0, y: 0 };
  return {
    x: (offsetX / width) * 2 - 1,
    y: -(offsetY / height) * 2 + 1,
  };
}

/**
 * Should lifting this pointer retract the ball immediately?
 *
 * A mouse keeps hovering after a click, so mouseup must NOT retract — the ball
 * stays under the cursor and the existing idle-frame countdown owns the
 * eventual park. Touch and pen have no hover: once the finger/stylus lifts the
 * pointer is simply gone, and leaving a kinematic ball parked inside the pile
 * for 90 frames would both look wrong and keep the pile awake. Same for
 * `pointercancel`, which is what a page scroll (touch-action: pan-y) sends.
 */
export function shouldRetractOnRelease(pointerType: string): boolean {
  return pointerType !== 'mouse';
}

/**
 * `touch-action` for the hero canvas.
 *
 * `pan-y` hands vertical drags to the browser so the landing page still
 * scrolls with a finger on the pile (breaking that is far worse than the bug
 * being fixed), while horizontal drags are delivered to us immediately with no
 * "is this a scroll?" arbitration delay — a lateral swipe through the logos is
 * exactly the shove gesture. `pinch-zoom` is kept so the page stays
 * pinch-zoomable; omitting it would silently disable zoom over the hero.
 */
export const HERO_TOUCH_ACTION = 'pan-y pinch-zoom';
