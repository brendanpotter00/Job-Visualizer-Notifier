import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StrictMode } from 'react';
import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useFetchWithStatus } from '../../hooks/useFetchWithStatus';

describe('useFetchWithStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('reports loading=true initially before the fetch resolves', () => {
    // Never-resolving promise so we can observe the initial state.
    const fetcher = vi.fn(() => new Promise<number>(() => {}));
    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('updates data after a successful fetch', async () => {
    const fetcher = vi.fn(async () => ({ hello: 'world' }));
    const { result } = renderHook(() =>
      useFetchWithStatus<{ hello: string }>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toEqual({ hello: 'world' });
    expect(result.current.error).toBeNull();
  });

  it('sets error via extractErrorMessage on a failed fetch', async () => {
    const fetcher = vi.fn(async () => {
      throw new Error('boom');
    });
    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('boom');
    expect(result.current.data).toBeNull();
  });

  it('re-fetches when deps change', async () => {
    const fetcher = vi.fn(async (_signal: AbortSignal) => 'ok');
    const { rerender } = renderHook(
      ({ dep }: { dep: string }) =>
        useFetchWithStatus<string>({ fetcher, deps: [dep] }),
      { initialProps: { dep: 'a' } }
    );

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    rerender({ dep: 'b' });

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
  });

  it('does NOT re-fetch when deps are unchanged across rerenders', async () => {
    const fetcher = vi.fn(async () => 1);
    const { rerender } = renderHook(
      ({ dep }: { dep: string }) =>
        useFetchWithStatus<number>({ fetcher, deps: [dep] }),
      { initialProps: { dep: 'stable' } }
    );

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    rerender({ dep: 'stable' });
    rerender({ dep: 'stable' });

    // Allow any queued microtasks to flush.
    await Promise.resolve();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('short-circuits when skip=true', async () => {
    const fetcher = vi.fn(async () => 42);
    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [], skip: true })
    );

    // skip=true means we never call the fetcher and loading starts at false.
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('reload() triggers a fresh fetch', async () => {
    const fetcher = vi.fn(async () => 'value');
    const { result } = renderHook(() =>
      useFetchWithStatus<string>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    act(() => {
      result.current.reload();
    });

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
  });

  it('aborts the in-flight request on unmount and does not set state', async () => {
    let capturedSignal: AbortSignal | null = null;
    // Never-resolving promise that captures the signal so we can assert on it.
    const fetcher = vi.fn(
      (signal: AbortSignal) =>
        new Promise<number>(() => {
          capturedSignal = signal;
        })
    );

    const { unmount, result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    // Fetch started.
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(capturedSignal).not.toBeNull();
    expect(capturedSignal!.aborted).toBe(false);

    unmount();

    expect(capturedSignal!.aborted).toBe(true);
    // No state change should have happened post-unmount.
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('passes an AbortSignal to the fetcher', async () => {
    const fetcher = vi.fn(async (signal: AbortSignal) => {
      expect(signal).toBeInstanceOf(AbortSignal);
      return 'ok';
    });
    renderHook(() => useFetchWithStatus<string>({ fetcher, deps: [] }));

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
    const firstCallArg = fetcher.mock.calls[0][0];
    expect(firstCallArg).toBeInstanceOf(AbortSignal);
  });

  it('surfaces a name-only AbortError thrown without an aborted signal (not swallowed)', async () => {
    // The hook gates abort detection on `controller.signal.aborted`. An Error
    // whose `name` happens to be `'AbortError'` but that is thrown without the
    // signal being aborted is a legitimate error (e.g. a backend surface or a
    // custom-fetcher class whose name collides with the DOM AbortError). It
    // must NOT be silently swallowed.
    const fetcher = vi.fn(async () => {
      const err = new Error('aborted');
      err.name = 'AbortError';
      throw err;
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('aborted');
  });

  it('surfaces a bare { name: "AbortError" } object thrown without an aborted signal', async () => {
    // Companion to the Error-instance case above: a plain object shaped like
    // `{ name: 'AbortError' }` thrown while the signal is still live must also
    // surface, rather than being swallowed by a name-only shape check.
    const fetcher = vi.fn(async () => {
      throw { name: 'AbortError', message: 'backend-reported abort' };
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('backend-reported abort');
  });

  it('treats a bare { name: "AbortError" } throw as an abort (not Error instance)', async () => {
    // Covers the older-engine case where `DOMException` is not an `Error`
    // subclass and custom fetchers throwing plain objects with name='AbortError'.
    const fetcher = vi.fn(
      (signal: AbortSignal) =>
        new Promise<number>((_resolve, reject) => {
          signal.addEventListener('abort', () => {
            // Bare object — intentionally not an Error instance.
            reject({ name: 'AbortError', message: 'aborted' });
          });
        })
    );

    const { result, unmount } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    // Abort the in-flight request.
    unmount();

    // Drain microtasks so the catch handler runs.
    await Promise.resolve();
    await Promise.resolve();

    expect(result.current.error).toBeNull();
  });

  it('aborts the prior request when deps change mid-flight (last fetch wins)', async () => {
    const signals: AbortSignal[] = [];
    let resolveFirst: ((value: string) => void) | null = null;
    const pendingFirst = new Promise<string>((res) => {
      resolveFirst = res;
    });

    const fetcher = vi.fn((signal: AbortSignal) => {
      signals.push(signal);
      if (signals.length === 1) return pendingFirst;
      return Promise.resolve('second');
    });

    const { result, rerender } = renderHook(
      ({ dep }: { dep: number }) =>
        useFetchWithStatus<string>({ fetcher, deps: [dep] }),
      { initialProps: { dep: 1 } }
    );

    // Kick off a second fetch before the first resolves.
    rerender({ dep: 2 });

    await waitFor(() => {
      expect(result.current.data).toBe('second');
    });

    // The first signal must have been aborted; the late resolution below
    // must not overwrite the 'second' result.
    expect(signals[0].aborted).toBe(true);
    resolveFirst!('first');

    await Promise.resolve();
    await Promise.resolve();

    expect(result.current.data).toBe('second');
    expect(result.current.error).toBeNull();
  });

  it('decodes string-thrown errors via extractErrorMessage', async () => {
    const fetcher = vi.fn(async () => {
      throw 'plain string failure';
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.error).toBe('plain string failure');
    });
  });

  it('decodes Error-instance errors via extractErrorMessage', async () => {
    const fetcher = vi.fn(async () => {
      throw new Error('http 500');
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.error).toBe('http 500');
    });
  });

  it('falls back to default message when thrown value is null/undefined', async () => {
    const fetcher = vi.fn(async () => {
      throw null;
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.error).toBe('Request failed');
    });
  });

  it('converges to a single successful fetch under React StrictMode double-mount', async () => {
    // StrictMode intentionally mounts-unmounts-remounts on dev. The first
    // mount's controller is aborted by the unmount, so the second mount's
    // fetch is the one that lands. We assert the fetcher is invoked (once or
    // twice — React may call it on each mount) and the final state reflects
    // a successful fetch.
    const fetcher = vi.fn(async () => 'ok');
    const wrapper = ({ children }: { children: ReactNode }) => (
      <StrictMode>{children}</StrictMode>
    );
    const { result } = renderHook(
      () => useFetchWithStatus<string>({ fetcher, deps: [] }),
      { wrapper }
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBe('ok');
    expect(result.current.error).toBeNull();
    // Under StrictMode React may call the fetcher on each mount; assert bounded.
    expect(fetcher.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(fetcher.mock.calls.length).toBeLessThanOrEqual(2);
  });

  it('decodes RTK-Query-shape { data: { detail } } errors via extractErrorMessage', async () => {
    const fetcher = vi.fn(async () => {
      throw { data: { detail: 'backend down' } };
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    await waitFor(() => {
      expect(result.current.error).toBe('backend down');
    });
  });

  it('aborts the first signal when reload() is called while the first fetch is pending', async () => {
    const signals: AbortSignal[] = [];
    let resolveFirst: ((v: string) => void) | null = null;
    const firstPending = new Promise<string>((res) => {
      resolveFirst = res;
    });

    const fetcher = vi.fn((signal: AbortSignal) => {
      signals.push(signal);
      if (signals.length === 1) return firstPending;
      return Promise.resolve('second');
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<string>({ fetcher, deps: [] })
    );

    // First fetch in flight; kick off reload() before it resolves.
    expect(fetcher).toHaveBeenCalledTimes(1);
    act(() => {
      result.current.reload();
    });

    await waitFor(() => {
      expect(result.current.data).toBe('second');
    });

    // The first signal must have been aborted by reload() before the second
    // fetch resolved. Assert this only after "second" has landed.
    expect(signals[0].aborted).toBe(true);

    // Belt-and-suspenders: the first promise resolving late must not clobber.
    resolveFirst!('first');
    await Promise.resolve();
    await Promise.resolve();
    expect(result.current.data).toBe('second');
  });
});
