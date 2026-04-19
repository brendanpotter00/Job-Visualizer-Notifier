import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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

  it('does not surface an AbortError as user-facing error state', async () => {
    const fetcher = vi.fn(async () => {
      const err = new Error('aborted');
      err.name = 'AbortError';
      throw err;
    });

    const { result } = renderHook(() =>
      useFetchWithStatus<number>({ fetcher, deps: [] })
    );

    // Give the microtask queue a chance to drain.
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
});
