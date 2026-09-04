import { useSyncExternalStore } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

/**
 * Whether the OS-level "reduce motion" preference is on.
 *
 * Hand-rolled instead of framer-motion's `useReducedMotion` because (a) jsdom
 * does not implement `window.matchMedia` at all, so the guard below is what
 * keeps tests alive, and (b) framer caches its listener in a module-level
 * singleton, which makes per-test toggling unreliable. `useSyncExternalStore`
 * subscribes without any set-state-in-effect pattern.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

function supported(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function';
}

function subscribe(onStoreChange: () => void): () => void {
  if (!supported()) return () => {};
  const mql = window.matchMedia(QUERY);
  mql.addEventListener('change', onStoreChange);
  return () => mql.removeEventListener('change', onStoreChange);
}

function getSnapshot(): boolean {
  return supported() ? window.matchMedia(QUERY).matches : false;
}

function getServerSnapshot(): boolean {
  return false;
}
