import { useEffect, useState } from 'react';

/** Upper bound on how long an idle callback may wait before firing anyway (ms). */
const IDLE_TIMEOUT_MS = 1500;

type IdleWindow = Window & {
  requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  cancelIdleCallback?: (id: number) => void;
};

/**
 * False on the first render; true once the page has painted and the browser
 * is idle (or IDLE_TIMEOUT_MS has passed). Gate heavy, decorative work on it —
 * the landing page's three/rapier scene — so the hero text paints first and
 * the scene's multi-megabyte download and parse never compete with it.
 *
 * rAF → setTimeout(0) lands after the frame that painted the first commit;
 * requestIdleCallback then waits for a quiet moment. Safari has no
 * requestIdleCallback, so it goes straight on after the paint.
 */
export function useAfterFirstPaint(): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const w = window as IdleWindow;
    let cancelled = false;
    let rafId: number | undefined;
    let timerId: number | undefined;
    let idleId: number | undefined;

    const markReady = () => {
      if (!cancelled) setReady(true);
    };
    const afterPaint = () => {
      if (cancelled) return;
      if (typeof w.requestIdleCallback === 'function') {
        idleId = w.requestIdleCallback(markReady, { timeout: IDLE_TIMEOUT_MS });
      } else {
        markReady();
      }
    };

    if (typeof w.requestAnimationFrame === 'function') {
      rafId = w.requestAnimationFrame(() => {
        timerId = window.setTimeout(afterPaint, 0);
      });
    } else {
      timerId = window.setTimeout(afterPaint, 0);
    }

    return () => {
      cancelled = true;
      if (rafId !== undefined) w.cancelAnimationFrame(rafId);
      if (timerId !== undefined) window.clearTimeout(timerId);
      if (idleId !== undefined) w.cancelIdleCallback?.(idleId);
    };
  }, []);

  return ready;
}
