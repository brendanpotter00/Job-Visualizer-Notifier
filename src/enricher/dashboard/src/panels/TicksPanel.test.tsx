import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, act } from "@testing-library/react";
import { TicksPanel } from "./TicksPanel";
import { mockFetch, renderWithTheme } from "../test/utils";

afterEach(() => {
  vi.useRealTimers();
});

const TICKS = {
  ticks: [
    {
      id: 5,
      uuid: null,
      started_at: "2026-01-01T00:00:00Z",
      ended_at: "2026-01-01T00:00:03Z",
      status: "ok",
      claimed: 10,
      cleaned: 10,
      classified: 10,
      judged: 0,
      corrected: 0,
      needs_human: 0,
      sent: 0,
      errors: 0,
      nulled_facets: 6, // >50% of classified -> drift
      notes: null,
      stage_timings: [],
      drift_suspected: true,
    },
  ],
};

describe("TicksPanel", () => {
  it("renders the recent ticks with the drift chip on a drifted tick", async () => {
    mockFetch({ "/api/ticks": { json: TICKS } });
    renderWithTheme(<TicksPanel />);

    await screen.findByText("#5");
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("drift")).toBeInTheDocument(); // the red drift chip
  });

  // Guards Ledger #2: after a successful first load, a later failed poll must
  // show the non-blocking UpdatesPaused banner WHILE the last-good data stays on
  // screen — it must NOT fall back to the first-load ErrorNote (the original
  // `if (error && !data)` guard swallowed all post-load poll failures silently).
  it("shows UpdatesPaused (keeping prior data) when a later poll fails", async () => {
    vi.useFakeTimers();
    let n = 0;
    mockFetch({
      "/api/ticks": () => (n++ === 0 ? { json: TICKS } : { ok: false, status: 500, json: {} }),
    });
    renderWithTheme(<TicksPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0); // flush the first (successful) load
    });

    expect(screen.getByText("#5")).toBeInTheDocument(); // data rendered
    expect(screen.queryByText(/Updates paused/)).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000); // poll interval fires -> 500
    });

    // the paused banner appears...
    expect(screen.getByText(/Updates paused/)).toBeInTheDocument();
    // ...the previously-loaded tick is still on screen...
    expect(screen.getByText("#5")).toBeInTheDocument();
    // ...and it did NOT collapse to the first-load ErrorNote.
    expect(screen.queryByText(/Failed to load/)).not.toBeInTheDocument();
  });
});
