/**
 * Frameloop governor for the Gravity scene (lives INSIDE the Canvas: needs
 * useThree). Three inputs feed the pure `resolveFrameloop` rule:
 *   1. rapier auto-sleep — an onSleep/onWake counter across every tile body,
 *   2. hero visibility — IntersectionObserver on the canvas element,
 *   3. tab visibility — document.visibilitychange.
 * When the pile has fully settled (or nobody can see it) the frameloop parks
 * at 'never': zero GPU/CPU until something changes. The jsdom test setup stubs
 * IntersectionObserver as a no-op class, so `heroInView` simply keeps its
 * default (true) there — degrade gracefully, never crash.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useStore, useThree } from '@react-three/fiber';
import { resolveFrameloop } from '../shared3d/experienceTier';

export interface SettleGovernor {
  /** Wire to every tile RigidBody's onSleep. */
  onBodySleep: () => void;
  /** Wire to every tile RigidBody's onWake. */
  onBodyWake: () => void;
  /** Re-run the frameloop decision from the current inputs. */
  refresh: () => void;
  /**
   * Interaction hint: force rendering back on (if visible) so the pointer
   * ball can stir a fully-asleep pile — sleep events alone can't restart a
   * parked frameloop because a parked loop never steps physics.
   */
  wake: () => void;
}

export function useSettleGovernor(bodyCount: number): SettleGovernor {
  const store = useStore();
  const gl = useThree((state) => state.gl);
  const size = useThree((state) => state.size);

  const asleepCountRef = useRef(0);
  const heroInViewRef = useRef(true);
  const docVisibleRef = useRef(
    typeof document === 'undefined' || document.visibilityState !== 'hidden'
  );

  /**
   * The ONLY way this hook touches the frameloop — and it never re-asserts a
   * mode that is already active. R3F's `setFrameloop` is not idempotent: every
   * call does `clock.stop(); clock.start()`, which resets `clock.oldTime` to
   * "now". `useFrame`'s delta is `clock.getDelta()`, so a redundant call
   * shortly before a frame reports a fraction of the real elapsed time. At
   * pointermove rates (60–120 Hz of `wake()`) that starves rapier's fixed-step
   * accumulator and the whole simulation runs in slow motion — measured 23
   * physics steps/s instead of 60 while sweeping the pointer through the pile.
   * R3F guards its own `frameloop` prop exactly this way.
   */
  const applyFrameloop = useCallback(
    (next: 'always' | 'never') => {
      const state = store.getState();
      if (state.frameloop !== next) state.setFrameloop(next);
    },
    [store]
  );

  const refresh = useCallback(() => {
    applyFrameloop(
      resolveFrameloop({
        allAsleep: bodyCount > 0 && asleepCountRef.current >= bodyCount,
        heroInView: heroInViewRef.current,
        docVisible: docVisibleRef.current,
      })
    );
  }, [bodyCount, applyFrameloop]);

  const onBodySleep = useCallback(() => {
    asleepCountRef.current = Math.min(asleepCountRef.current + 1, bodyCount);
    refresh();
  }, [bodyCount, refresh]);

  const onBodyWake = useCallback(() => {
    asleepCountRef.current = Math.max(asleepCountRef.current - 1, 0);
    refresh();
  }, [refresh]);

  const wake = useCallback(() => {
    if (heroInViewRef.current && docVisibleRef.current) applyFrameloop('always');
  }, [applyFrameloop]);

  /**
   * Re-assert the decision on mount and after every canvas geometry change.
   * Two distinct reasons, one effect:
   *
   * 1. Mount. A fresh governor starts with an empty sleep tally, but the
   *    frameloop is shared canvas state that may still be parked at 'never'
   *    from the pile this one replaced (GravityPile remounts on resize) — and
   *    a parked loop never steps physics, so nothing else would restart it.
   * 2. Resize/scroll. R3F re-runs `root.configure()` on every render of its
   *    <Canvas> — which `useMeasure` triggers on resize AND on scroll (it
   *    tracks `top`) — and configure unconditionally re-asserts the
   *    `frameloop` *prop*: `if (state.frameloop !== frameloop) setFrameloop()`.
   *    That silently un-parks a settled pile and burns 60fps forever, since
   *    nothing else would ever revisit the decision. `state.size` changes on
   *    exactly those geometry updates, so keying on it re-parks right after
   *    R3F has clobbered us (configure is synchronous past the one-time
   *    renderer setup, so this passive effect always runs after it).
   *
   * Idempotent either way: `applyFrameloop` no-ops when the mode matches.
   */
  useEffect(() => {
    refresh();
  }, [size, refresh]);

  useEffect(() => {
    if (typeof IntersectionObserver !== 'function') return undefined;
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (entry) {
        heroInViewRef.current = entry.isIntersecting;
        refresh();
      }
    });
    observer.observe(gl.domElement);
    return () => observer.disconnect();
  }, [gl, refresh]);

  useEffect(() => {
    const handleVisibility = () => {
      docVisibleRef.current = document.visibilityState !== 'hidden';
      refresh();
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [refresh]);

  return useMemo(
    () => ({ onBodySleep, onBodyWake, refresh, wake }),
    [onBodySleep, onBodyWake, refresh, wake]
  );
}
