import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobsPanel } from "./JobsPanel";
import { mockFetch, renderWithTheme } from "../test/utils";

const ROW = {
  source_id: "greenhouse",
  job_listing_id: "1",
  title: "Senior SWE",
  company: "Acme",
  raw_location: "San Francisco, CA",
  status: "enriched",
  claimed_at: "2026-01-01T00:00:00Z",
  category: "software_engineering",
  level: "senior",
  classify_confidence: 0.9,
  judged: 0,
  judge_pass: null,
  needs_human: 1,
  tick_id: 1,
  enriched_at: "2026-01-01T00:00:00Z",
  sent_at: null,
};

// total > pageSize so the DataGrid exposes a "next page" control we can drive.
const JOBS = { jobs: [ROW], total: 60, limit: 25, offset: 0 };

// mockFetch matches by first substring hit, so "/api/jobs" MUST be registered
// before "/api/job" (a /api/jobs? URL contains both; a /api/job? URL only the latter).
const lastJobsUrl = (fetchFn: ReturnType<typeof mockFetch>): string => {
  const calls = fetchFn.mock.calls.filter(([u]) => String(u).includes("/api/jobs"));
  return String(calls[calls.length - 1][0]);
};

describe("JobsPanel", () => {
  it("renders the filter controls and the grid columns, and loads jobs from the API", async () => {
    const fetchFn = mockFetch({ "/api/jobs": { json: { ...JOBS, total: 1 } } });
    renderWithTheme(<JobsPanel />);

    // filter controls
    expect(screen.getByLabelText("State")).toBeInTheDocument();
    expect(screen.getByText("needs human only")).toBeInTheDocument();

    // DataGrid columns render regardless of row virtualization in jsdom
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Company")).toBeInTheDocument();

    // it fetched /api/jobs with a pagination limit
    await waitFor(() => expect(fetchFn).toHaveBeenCalled());
    expect(String(fetchFn.mock.calls[0][0])).toContain("/api/jobs?");
    expect(String(fetchFn.mock.calls[0][0])).toContain("limit=25");

    // the seeded row surfaces in the grid
    expect(await screen.findByText("Senior SWE")).toBeInTheDocument();
  });

  it("changing the status filter refetches with status= and resets to page 0", async () => {
    const fetchFn = mockFetch({ "/api/jobs": { json: JOBS } });
    renderWithTheme(<JobsPanel />);
    await screen.findByText("Senior SWE");

    // move off page 0 first so the reset is observable via offset
    await userEvent.click(screen.getByRole("button", { name: /next page/i }));
    await waitFor(() => expect(lastJobsUrl(fetchFn)).toContain("offset=25"));

    // pick a State -> refetch carries the status param AND snaps offset back to 0
    await userEvent.click(screen.getByLabelText("State"));
    await userEvent.click(await screen.findByRole("option", { name: "sent" }));

    await waitFor(() => {
      const url = lastJobsUrl(fetchFn);
      expect(url).toContain("status=sent");
      expect(url).toContain("offset=0");
    });
  });

  it("toggling the needs-human switch refetches with needs_human=true", async () => {
    const fetchFn = mockFetch({ "/api/jobs": { json: { ...JOBS, total: 1 } } });
    renderWithTheme(<JobsPanel />);
    await screen.findByText("Senior SWE");

    await userEvent.click(screen.getByRole("checkbox")); // the only Switch
    await waitFor(() => expect(lastJobsUrl(fetchFn)).toContain("needs_human=true"));
  });

  it("renders ErrorNote when the jobs fetch fails", async () => {
    mockFetch({ "/api/jobs": { ok: false, status: 500, json: {} } });
    renderWithTheme(<JobsPanel />);
    expect(await screen.findByText(/Failed to load: 500/)).toBeInTheDocument();
  });

  it("opens the detail drawer with fetched entries on a row click", async () => {
    const fetchFn = mockFetch({
      "/api/jobs": { json: { ...JOBS, total: 1 } },
      "/api/job": { json: { category: "software_engineering", clean_description: "build things" } },
    });
    renderWithTheme(<JobsPanel />);
    await screen.findByText("Senior SWE");

    await userEvent.click(screen.getByText("Senior SWE")); // row click

    // fetchJobDetail hit /api/job for the clicked row's composite id
    await waitFor(() =>
      expect(fetchFn.mock.calls.some(([u]) => String(u).includes("/api/job?"))).toBe(true),
    );
    const detailUrl = String(fetchFn.mock.calls.find(([u]) => String(u).includes("/api/job?"))![0]);
    expect(detailUrl).toContain("source_id=greenhouse");
    expect(detailUrl).toContain("job_listing_id=1");

    // the Drawer opened and rendered the detail entries
    expect(await screen.findByText("Job detail")).toBeInTheDocument();
    expect(await screen.findByText("clean_description")).toBeInTheDocument();
  });

  // Guards Ledger #3: openDetail must surface non-404 detail-fetch failures
  // (rather than the original bare `catch {}` that turned every row click into a
  // silent no-op during an outage). A revert to swallow-all fails this test.
  it("surfaces an ErrorNote when the detail fetch fails with a 500", async () => {
    mockFetch({
      "/api/jobs": { json: { ...JOBS, total: 1 } },
      "/api/job": { ok: false, status: 500, json: {} },
    });
    renderWithTheme(<JobsPanel />);
    await screen.findByText("Senior SWE");

    await userEvent.click(screen.getByText("Senior SWE")); // row click -> 500

    // the non-404 failure is surfaced, not swallowed...
    expect(await screen.findByText(/Failed to load: 500/)).toBeInTheDocument();
    // ...and the detail drawer never opened.
    expect(screen.queryByText("Job detail")).not.toBeInTheDocument();
  });

  // Guards Ledger #3 (the other direction): a 404 means the row vanished between
  // list and detail — it is silently ignored by design (no drawer, no error).
  it("silently ignores a 404 detail fetch: drawer stays closed, no error shown", async () => {
    const fetchFn = mockFetch({
      "/api/jobs": { json: { ...JOBS, total: 1 } },
      "/api/job": { ok: false, status: 404, json: {} },
    });
    renderWithTheme(<JobsPanel />);
    await screen.findByText("Senior SWE");

    await userEvent.click(screen.getByText("Senior SWE")); // row click -> 404

    // the detail fetch was attempted for the clicked row...
    await waitFor(() =>
      expect(fetchFn.mock.calls.some(([u]) => String(u).includes("/api/job?"))).toBe(true),
    );
    // ...but a 404 is swallowed: the drawer stays closed and no error banner shows.
    expect(screen.queryByText("Job detail")).not.toBeInTheDocument();
    expect(screen.queryByText(/Failed to load/)).not.toBeInTheDocument();
  });
});
