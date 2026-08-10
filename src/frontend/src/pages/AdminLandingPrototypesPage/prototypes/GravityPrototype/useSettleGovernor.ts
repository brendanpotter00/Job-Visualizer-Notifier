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
import { useThree } from '@react-three/fiber';
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
  const setFrameloop = useThree((state) => state.setFrameloop);
  const gl = useThree((state) => state.gl);

  const asleepCountRef = useRef(0);
  const heroInViewRef = useRef(true);
  const docVisibleRef = useRef(
    typeof document === 'undefined' || document.visibilityState !== 'hidden'
  );

  const refresh = useCallback(() => {
    setFrameloop(
      resolveFrameloop({
        allAsleep: bodyCount > 0 && asleepCountRef.current >= bodyCount,
        heroInView: heroInViewRef.current,
        docVisible: docVisibleRef.current,
      })
    );
  }, [bodyCount, setFrameloop]);

  const onBodySleep = useCallback(() => {
    asleepCountRef.current = Math.min(asleepCountRef.current + 1, bodyCount);
    refresh();
  }, [bodyCount, refresh]);

  const onBodyWake = useCallback(() => {
    asleepCountRef.current = Math.max(asleepCountRef.current - 1, 0);
    refresh();
  }, [refresh]);

  const wake = useCallback(() => {
    if (heroInViewRef.current && docVisibleRef.current) setFrameloop('always');
  }, [setFrameloop]);

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
