import { useEffect, useState } from 'react';

/**
 * Returns a debounced copy of ``value`` that only updates after ``delayMs``
 * of no further changes. Used by the alias browser so server-side search
 * fires once per typing pause rather than per keystroke.
 *
 * @param value - The fast-changing source value (e.g. a controlled input).
 * @param delayMs - Quiet period (ms) before the debounced value catches up.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);

  return debounced;
}
