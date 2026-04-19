import { useCallback, useEffect, useRef, useState } from 'react';
import { extractErrorMessage } from '../lib/errors';

/**
 * Options for {@link useFetchWithStatus}.
 *
 * @template T  Shape of the successful response payload.
 */
export interface FetchWithStatusOptions<T> {
  /**
   * Called on mount and whenever any key in {@link FetchWithStatusOptions.deps}
   * changes. Must be a stable reference (wrap in `useCallback` at the call site);
   * otherwise the hook will re-fetch every render.
   *
   * The provided `signal` is plumbed through so the hook can abort in-flight
   * requests when `deps` change, when `reload()` is called, or when the
   * component unmounts.
   */
  fetcher: (signal: AbortSignal) => Promise<T>;

  /**
   * Controls when the hook re-fetches. Semantically identical to `useEffect`
   * deps — when any entry changes (by `Object.is`), a new fetch is issued and
   * the prior one is aborted.
   */
  deps: ReadonlyArray<unknown>;

  /**
   * Skip the fetch entirely. While `true`, the hook returns
   * `{ data: null, loading: false, error: null }` and never issues a request.
   *
   * Default: `false`.
   */
  skip?: boolean;
}

/**
 * Return shape of {@link useFetchWithStatus}.
 */
export interface FetchWithStatusResult<T> {
  /** Most recent successful payload, or `null` before the first success. */
  data: T | null;

  /** `true` while a fetch is in flight. */
  loading: boolean;

  /** Decoded error message from the most recent failed fetch, or `null`. */
  error: string | null;

  /**
   * Force a re-fetch using the current `deps`. Prior in-flight requests are
   * aborted. Calling `reload()` on an unmounted component is a no-op.
   */
  reload: () => void;
}

/**
 * Generic abortable fetch-lifecycle hook for page-level data loads.
 *
 * Uses the AbortController + mountedRef pattern to prevent stale responses
 * from overwriting state after the component unmounts or the deps change.
 * When deps change mid-flight, the prior request is aborted so "last fetch
 * wins" — the user never sees a late response clobber the current one.
 *
 * @example
 * const { data, loading, error, reload } = useFetchWithStatus<Job[]>({
 *   fetcher: (signal) => fetch(`/api/jobs`, { signal }).then((r) => r.json()),
 *   deps: [selectedCompany],
 * });
 */
export function useFetchWithStatus<T>(
  options: FetchWithStatusOptions<T>
): FetchWithStatusResult<T> {
  const { fetcher, deps, skip = false } = options;

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(!skip);
  const [error, setError] = useState<string | null>(null);

  // Tracks whether the hosting component is still mounted. Prevents
  // setState-after-unmount warnings if a fetch resolves late.
  const mountedRef = useRef<boolean>(true);

  // Active controller for the in-flight request; aborted on deps-change,
  // reload(), and unmount.
  const activeController = useRef<AbortController | null>(null);

  // Internal "reload" counter spread into the effect's deps so calling
  // reload() forces a re-run without requiring the caller to mutate `deps`.
  const [reloadCounter, setReloadCounter] = useState<number>(0);

  const reload = useCallback(() => {
    if (!mountedRef.current) return;
    setReloadCounter((prev) => prev + 1);
  }, []);

  useEffect(() => {
    // `skip` short-circuit: leave data/error/loading in their "idle" shape.
    if (skip) {
      activeController.current?.abort();
      activeController.current = null;
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }

    // Abort any prior in-flight request before starting a new one.
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;

    setLoading(true);
    setError(null);

    fetcher(controller.signal)
      .then((result) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        setData(result);
        setError(null);
        setLoading(false);
      })
      .catch((err) => {
        if (!mountedRef.current) return;
        // Treat anything thrown while the controller is aborted as an abort —
        // covers native `DOMException` (not an `Error` subclass on older
        // engines) as well as bare `{ name: 'AbortError' }` objects thrown by
        // custom fetchers. Falls back to a name-only shape check so aborts
        // thrown without an aborted signal (uncommon but legal) still exit
        // silently.
        const isAbortError =
          controller.signal.aborted ||
          (err != null &&
            typeof err === 'object' &&
            'name' in err &&
            (err as { name?: unknown }).name === 'AbortError');
        if (isAbortError) return;
        setError(extractErrorMessage(err, 'Request failed'));
        setLoading(false);
      });

    return () => {
      controller.abort();
    };
    // `deps` is spread into the effect dep list; the lint rule cannot prove
    // the spread is stable-by-convention across renders, so we disable it here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetcher, skip, reloadCounter, ...deps]);

  // Mount/unmount tracking. Separate effect so the fetch effect's cleanup
  // aborts the current controller BEFORE this effect flips mountedRef.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeController.current?.abort();
      activeController.current = null;
    };
  }, []);

  return { data, loading, error, reload };
}
