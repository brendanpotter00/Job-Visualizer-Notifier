import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useApi } from "./useApi";

const res = (json: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => json }) as Response;

afterEach(() => {
  vi.useRealTimers();
});

describe("useApi", () => {
  it("fetches once on mount, then exposes data and clears loading", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => res({ hello: "world" })));
    const { result } = renderHook(() => useApi<{ hello: string }>("/api/x"));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ hello: "world" });
    expect(result.current.error).toBeNull();
  });

  it("surfaces the status code as an error on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => res({}, false, 503)));
    const { result } = renderHook(() => useApi("/api/x"));
    await waitFor(() => expect(result.current.error).toBe("503"));
    expect(result.current.data).toBeNull();
  });

  it("keeps the last-good data (and sets error) when a subsequent poll fails", async () => {
    vi.useFakeTimers();
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(res({ n: 1 })) // mount: succeeds
      .mockResolvedValueOnce(res({}, false, 500)); // next poll: fails
    vi.stubGlobal("fetch", fetchFn);

    const { result } = renderHook(() => useApi<{ n: number }>("/api/x", 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0); // flush the mount fetch
    });
    expect(result.current.data).toEqual({ n: 1 });
    expect(result.current.error).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // interval fires -> failing poll
    });

    // The failed poll must NOT wipe the last-good data — it only sets error.
    // This is the load-bearing invariant for the disconnected chip (Ledger #1)
    // and the UpdatesPaused banner (Ledger #2). A regression that added
    // setData(null) to useApi's catch would fail this assertion.
    expect(result.current.data).toEqual({ n: 1 });
    expect(result.current.error).toBe("500");
  });

  it("aborts the in-flight request on refresh and ignores its (aborted) result", async () => {
    const signals: AbortSignal[] = [];
    const fetchFn = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      const signal = init!.signal!;
      signals.push(signal);
      if (signals.length === 1) {
        // first request settles only by aborting — mirrors real fetch(), which
        // rejects an aborted request (so the try-block setData is never reached).
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
      }
      return Promise.resolve(res({ n: 2 }));
    });
    vi.stubGlobal("fetch", fetchFn);

    const { result } = renderHook(() => useApi<{ n: number }>("/api/x"));
    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(1));

    await act(async () => {
      result.current.refresh(); // aborts request 1, starts request 2
    });
    await waitFor(() => expect(result.current.data).toEqual({ n: 2 }));

    expect(signals[0].aborted).toBe(true); // first controller was aborted
    expect(result.current.error).toBeNull(); // aborted rejection did not set error
  });

  it("polls on the interval but skips ticks while the tab is hidden", async () => {
    vi.useFakeTimers();
    let hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    const fetchFn = vi.fn(async () => res({ ok: 1 }));
    vi.stubGlobal("fetch", fetchFn);

    const { unmount } = renderHook(() => useApi("/api/x", 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0); // flush the mount fetch
    });
    expect(fetchFn).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // visible -> polls
    });
    expect(fetchFn).toHaveBeenCalledTimes(2);

    hidden = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // hidden -> skipped
    });
    expect(fetchFn).toHaveBeenCalledTimes(2);

    hidden = false;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // visible again -> resumes
    });
    expect(fetchFn).toHaveBeenCalledTimes(3);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000); // no polling after unmount
    });
    expect(fetchFn).toHaveBeenCalledTimes(3);
    hidden = false;
  });
});
