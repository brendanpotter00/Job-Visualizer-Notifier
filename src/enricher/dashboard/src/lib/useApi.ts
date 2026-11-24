import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

/**
 * Fetch `path` once on mount and, if `intervalMs` is given, poll it — pausing
 * whenever the tab is hidden so we don't hammer SQLite in the background. In-
 * flight requests are aborted on refresh/unmount. No Convex/WebSocket here; the
 * data changes on the tick cadence, so short-interval polling is plenty.
 */
export function useApi<T>(path: string, intervalMs?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const acRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    acRef.current?.abort();
    const ac = new AbortController();
    acRef.current = ac;
    try {
      const res = await fetch(path, { signal: ac.signal });
      if (!res.ok) throw new Error(`${res.status}`);
      setData((await res.json()) as T);
      setError(null);
    } catch (e) {
      if (!ac.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    refresh();
    if (!intervalMs) return;
    const id = setInterval(() => {
      if (!document.hidden) refresh();
    }, intervalMs);
    return () => {
      clearInterval(id);
      acRef.current?.abort();
    };
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}
