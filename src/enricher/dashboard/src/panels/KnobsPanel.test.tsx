import { describe, it, expect } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KnobsPanel } from "./KnobsPanel";
import { mockFetch, renderWithTheme } from "../test/utils";

const KNOBS = {
  snapshot: {
    classify_engine: "claude-code",
    classify_model: "sonnet",
    classify_batch_size: 3,
    classify_fan_out: 12,
    judge_enabled: true,
    judge_engine: "claude-code",
    judge_model: "sonnet",
    judge_human_floor: 0.6,
    judge_scope: "low_confidence",
    judge_confidence_ceiling: 0.85,
    opencode_model: "qwen3:32b",
  },
  meta: {
    models: ["haiku", "sonnet", "opus"],
    engines: ["claude-code", "ollama", "opencode"],
    judge_scopes: ["all", "low_confidence"],
    classify_batch_bounds: [1, 10],
    classify_fanout_bounds: [1, 20],
    categories: ["software_engineering"],
    levels: ["senior"],
    taxonomy_version: "v1+test",
  },
};

// GET returns the snapshot+meta; POST echoes an updated snapshot reflecting the
// posted knob (or fails, per `postFails`).
function knobsRoutes(opts: { postFails?: boolean } = {}) {
  const counts = { get: 0, post: 0 };
  const fetchFn = mockFetch({
    "/api/knobs": (_url, init) => {
      if (init?.method === "POST") {
        counts.post++;
        if (opts.postFails) {
          return { ok: false, status: 400, json: { detail: "judge is locked" } };
        }
        const body = JSON.parse(init.body as string) as { key: string; value: unknown };
        return { json: { snapshot: { ...KNOBS.snapshot, [body.key]: body.value } } };
      }
      counts.get++;
      return { json: KNOBS };
    },
  });
  return { fetchFn, counts };
}

const posts = (fetchFn: ReturnType<typeof mockFetch>) =>
  fetchFn.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");

describe("KnobsPanel", () => {
  it("persists a change via postKnob and adopts the server snapshot", async () => {
    const { fetchFn } = knobsRoutes();
    renderWithTheme(<KnobsPanel />);
    await screen.findByText("Classify"); // GET resolved -> panel rendered

    const toggle = screen.getByRole("checkbox"); // judge_enabled (the only Switch)
    expect(toggle).toBeChecked();

    await userEvent.click(toggle);

    await waitFor(() => expect(toggle).not.toBeChecked()); // adopted server snapshot
    const post = posts(fetchFn);
    expect(post).toHaveLength(1);
    expect(JSON.parse(post[0][1]!.body as string)).toMatchObject({
      key: "judge_enabled",
      value: false,
    });
  });

  it("shows the Rejected toast and refetches (snap-back) when a save fails", async () => {
    const { fetchFn, counts } = knobsRoutes({ postFails: true });
    renderWithTheme(<KnobsPanel />);
    await screen.findByText("Classify");
    expect(counts.get).toBe(1);

    const toggle = screen.getByRole("checkbox");
    await userEvent.click(toggle);

    // the server's 400 detail surfaces in the Snackbar
    await screen.findByText(/Rejected: judge is locked/);
    // refresh() re-fetched to snap back to server truth...
    await waitFor(() => expect(counts.get).toBe(2));
    // ...and the failed toggle never stuck (server still says enabled)
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(posts(fetchFn)).toHaveLength(1);
  });

  // Guards R3-I1 (Ledger #13): a slider commit that fails during a SUSTAINED
  // outage — the POST fails AND the follow-up refresh() GET also fails — must
  // still snap the optimistic value back to the last-known-good server value
  // (the `refresh()` snap-back silently no-ops here because useApi keeps the
  // same `data` ref on a failed GET, so the `[data]` effect never re-runs), and
  // the frozen-data UpdatesPaused banner must appear. Reverting either half of
  // the fix fails this test.
  it("snaps a slider back to the server value and shows UpdatesPaused when the commit and refresh both fail", async () => {
    let gets = 0;
    mockFetch({
      "/api/knobs": (_url, init) => {
        // sustained outage: every POST (the commit) fails with a non-400 500
        if (init?.method === "POST") return { ok: false, status: 500, json: { detail: "boom" } };
        gets++;
        // the mount GET succeeds; the refresh() GET after the failed commit
        // also fails, so useApi keeps its last-good `data` (Ledger #11).
        return gets === 1 ? { json: KNOBS } : { ok: false, status: 500, json: {} };
      },
    });
    renderWithTheme(<KnobsPanel />);
    await screen.findByText("Classify"); // mount GET resolved (server value S=3)

    const batchLabel = (n: number) =>
      screen.getByText((t) => t.startsWith("Batch size") && t.endsWith(String(n)));
    const queryBatchLabel = (n: number) =>
      screen.queryByText((t) => t.startsWith("Batch size") && t.endsWith(String(n)));
    expect(batchLabel(3)).toBeInTheDocument();

    // optimistic drag to V=7 + commit (one fireEvent.change fires both onChange
    // and onChangeCommitted, as the happy-path slider test above relies on)
    const batch = screen.getAllByRole("slider")[0];
    fireEvent.change(batch, { target: { value: "7" } });
    expect(batchLabel(7)).toBeInTheDocument(); // optimistic value shows first

    // once the commit POST fails AND the refresh GET also fails: the frozen-data
    // banner appears AND the slider label snaps back to the server value S=3
    // (it does NOT stay stuck at the optimistic V=7).
    await screen.findByText(/Updates paused/);
    await waitFor(() => expect(batchLabel(3)).toBeInTheDocument());
    expect(queryBatchLabel(7)).toBeNull();
  });

  it("updates a slider's label (setLocal) and persists the right knob on commit", async () => {
    const { fetchFn } = knobsRoutes();
    renderWithTheme(<KnobsPanel />);
    await screen.findByText("Classify");

    const batchLabel = (n: number) =>
      screen.getByText((t) => t.startsWith("Batch size") && t.endsWith(String(n)));
    expect(batchLabel(3)).toBeInTheDocument();

    // first slider in DOM order is Classify → Batch size
    const batch = screen.getAllByRole("slider")[0];
    fireEvent.change(batch, { target: { value: "7" } });

    // onChange → setLocal reflected the new value in the label...
    expect(batchLabel(7)).toBeInTheDocument();
    // ...and the commit persisted that exact knob + value via postKnob
    await waitFor(() => expect(posts(fetchFn)).toHaveLength(1));
    expect(JSON.parse(posts(fetchFn)[0][1]!.body as string)).toMatchObject({
      key: "classify_batch_size",
      value: 7,
    });
  });

  // Guards R4-I1 (Ledger #14): the rollback source must be the last COMMITTED
  // server value, NOT the frozen mount value. Two saves on the SAME key: the
  // first commits C=5 (server + refresh GET agree on 5); the second, during a
  // sustained outage, optimistically moves to V=8 then fails. The control must
  // snap back to C=5 — not S=3 (the pre-fix `data.snapshot` mount value) and not
  // the optimistic V=8. Pre-fix code (rollback from a mount-frozen `data.snapshot`
  // with no success-path refresh) shows S=3 here and fails at the C=5 assertion.
  it("rolls a slider back to the last COMMITTED value (not the mount value) after a prior successful save", async () => {
    let serverBatch = 3; // value a successful GET reflects (S=3 at mount)
    let outage = false; // sustained outage begins at the 2nd (failing) commit
    let posts = 0;
    mockFetch({
      "/api/knobs": (_url, init) => {
        if (init?.method === "POST") {
          posts++;
          if (posts === 1) {
            serverBatch = 5; // first commit succeeds → server now holds C=5
            return { json: { snapshot: { ...KNOBS.snapshot, classify_batch_size: 5 } } };
          }
          outage = true; // second commit fails; the outage is now sustained
          return { ok: false, status: 500, json: { detail: "boom" } };
        }
        // GET: fails once the outage is underway (so useApi keeps last-good data,
        // Ledger #11); otherwise reflects the current committed server value.
        if (outage) return { ok: false, status: 500, json: {} };
        return {
          json: { snapshot: { ...KNOBS.snapshot, classify_batch_size: serverBatch }, meta: KNOBS.meta },
        };
      },
    });
    renderWithTheme(<KnobsPanel />);
    await screen.findByText("Classify");

    const batchLabel = (n: number) =>
      screen.getByText((t) => t.startsWith("Batch size") && t.endsWith(String(n)));
    const queryBatchLabel = (n: number) =>
      screen.queryByText((t) => t.startsWith("Batch size") && t.endsWith(String(n)));
    expect(batchLabel(3)).toBeInTheDocument(); // mount server value S=3

    const batch = screen.getAllByRole("slider")[0];

    // FIRST save: commit C=5. POST returns 5 and the success-path refresh GET
    // also returns 5, so the control settles on the committed value.
    fireEvent.change(batch, { target: { value: "5" } });
    await waitFor(() => expect(batchLabel(5)).toBeInTheDocument());

    // SECOND save: optimistically move to V=8, then the commit POST 500s AND the
    // follow-up refresh GET 500s (sustained outage → useApi keeps last-good data).
    fireEvent.change(batch, { target: { value: "8" } });
    expect(batchLabel(8)).toBeInTheDocument(); // optimistic value shows first

    await screen.findByText(/Updates paused/);
    // The fix: snaps back to the last COMMITTED value C=5 — NOT the mount value
    // S=3 (the pre-fix rollback source) and NOT the optimistic V=8.
    await waitFor(() => expect(batchLabel(5)).toBeInTheDocument());
    expect(queryBatchLabel(3)).toBeNull();
    expect(queryBatchLabel(8)).toBeNull();
  });

  // Guards the coupled banner-clear (Ledger #14): after an outage lights the
  // UpdatesPaused banner, a later SUCCESSFUL save must clear it (the POST proves
  // reachability; the success-path refresh GET re-syncs and clears useApi's
  // `error`). Removing the success-path refresh leaves the banner lingering →
  // this test fails at the final "banner gone" assertion.
  it("clears a lingering UpdatesPaused banner once a later save proves the API reachable", async () => {
    let recovered = false; // API comes back on the 2nd (succeeding) commit
    let posts = 0;
    mockFetch({
      "/api/knobs": (_url, init) => {
        if (init?.method === "POST") {
          posts++;
          if (posts === 1) return { ok: false, status: 500, json: { detail: "boom" } };
          recovered = true; // second commit succeeds → API reachable again
          const body = JSON.parse(init.body as string) as { key: string; value: unknown };
          return { json: { snapshot: { ...KNOBS.snapshot, [body.key]: body.value } } };
        }
        // GET: mount succeeds; the refresh after the failed 1st commit fails
        // (outage → banner); once recovered, GETs succeed again (banner clears).
        if (posts >= 1 && !recovered) return { ok: false, status: 500, json: {} };
        return { json: KNOBS };
      },
    });
    renderWithTheme(<KnobsPanel />);
    await screen.findByText("Classify");

    const toggle = screen.getByRole("checkbox"); // judge_enabled (the only Switch)
    // First save fails and its refresh GET fails → the outage banner appears.
    await userEvent.click(toggle);
    await screen.findByText(/Updates paused/);

    // A second save succeeds; its follow-up refresh GET succeeds → the banner
    // (useApi's `error`) is cleared.
    await userEvent.click(toggle);
    await waitFor(() => expect(screen.queryByText(/Updates paused/)).toBeNull());
  });
});
