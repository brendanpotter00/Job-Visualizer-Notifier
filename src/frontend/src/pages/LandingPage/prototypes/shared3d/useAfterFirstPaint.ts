import { useEffect, useState } from 'react';

const IDLE_TIMEOUT_MS = 1500;

type IdleWindow = Window & {
  requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  cancelIdleCallback?: (id: number) => void;
};

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
