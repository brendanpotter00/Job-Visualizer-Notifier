import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, act, within } from "@testing-library/react";
import { HealthPanel } from "./HealthPanel";
import { mockFetch, renderWithTheme } from "../test/utils";

afterEach(() => {
  vi.useRealTimers();
});

const HEALTH = {
  inbox: { claimed: 1, cleaned: 0, enriched: 2, sent: 3, failed: 0 },
  unsent: 2,
  needs_human: 4,
  failed_rows: 0,
  last_heartbeat_at: "2026-01-01T00:00:00Z",
  last_heartbeat_age_s: 12,
  stage_timings: [{ stage: "classify", runs: 3, avg_ms: 1200, items: 30, retries: 1 }],
  classify_engine: "ollama",
  classify_model: "haiku",
  judge_engine: "ollama",
  judge_model: "sonnet",
  opencode_model: "qwen3:32b",
  latest_tick: {
    id: 7,
    status: "ok",
    classified: 10,
    judged: 2,
    sent: 3,
    errors: 0,
  },
};

describe("HealthPanel", () => {
  it("renders inbox tiles, the needs-human count, liveness and stage timings", async () => {
    mockFetch({ "/api/health": { json: HEALTH } });
    renderWithTheme(<HealthPanel />);

    // section wiring
    await screen.findByText("Backlog & review");
    expect(screen.getByText("Liveness")).toBeInTheDocument();

    // needs-human tile value from the payload
    expect(screen.getByText("4")).toBeInTheDocument();
    // cumulative stage-timings table row (scoped: "classify" also appears in
    // the Inference row's engine label above)
    expect(within(screen.getByRole("table")).getByText("classify")).toBeInTheDocument();
    // latest-tick summary chip/id
    expect(screen.getByText("#7")).toBeInTheDocument();
  });

  // The Inference row is the one place an operator can confirm what's actually
  // running — must show the ENGINE, not just the (possibly-inert) Claude-tier
  // model, so an ollama deployment doesn't look like it's on Anthropic models.
  it("shows the live engine + open-model tag in the Inference row", async () => {
    mockFetch({ "/api/health": { json: HEALTH } });
    renderWithTheme(<HealthPanel />);

    await screen.findByText("Inference · what's actually running");
    // classify and judge each render their own engine/model pairing
    expect(screen.getAllByText("ollama · qwen3:32b")).toHaveLength(2);
  });

  // Guards Ledger #2: after a successful first load, a later failed poll must
  // show the non-blocking UpdatesPaused banner WHILE the last-good data stays on
  // screen — it must NOT fall back to the first-load ErrorNote (the original
  // `if (error && !data)` guard swallowed all post-load poll failures silently).
  it("shows UpdatesPaused (keeping prior data) when a later poll fails", async () => {
    vi.useFakeTimers();
    let n = 0;
    mockFetch({
      "/api/health": () => (n++ === 0 ? { json: HEALTH } : { ok: false, status: 500, json: {} }),
    });
    renderWithTheme(<HealthPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0); // flush the first (successful) load
    });

    expect(screen.getByText("#7")).toBeInTheDocument(); // data rendered
    expect(screen.queryByText(/Updates paused/)).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000); // poll interval fires -> 500
    });

    // the paused banner appears...
    expect(screen.getByText(/Updates paused/)).toBeInTheDocument();
    // ...the previously-loaded data is still on screen...
    expect(screen.getByText("#7")).toBeInTheDocument();
    // ...and it did NOT collapse to the first-load ErrorNote.
    expect(screen.queryByText(/Failed to load/)).not.toBeInTheDocument();
  });
});
