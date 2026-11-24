import { describe, it, expect } from "vitest";
import { fmtAge, fmtConfidence, fmtDurationMs, fmtTs, tickDuration } from "./format";

describe("fmtAge", () => {
  it("returns em dash for null", () => {
    expect(fmtAge(null)).toBe("—");
  });
  it("clamps negatives to 0s", () => {
    expect(fmtAge(-5)).toBe("0s");
  });
  it.each([
    [0, "0s"],
    [59, "59s"],
    [60, "1m"],
    [3599, "60m"], // 3599/60 rounds to 60 before crossing the hour boundary
    [3600, "1h"],
    [86399, "24h"], // 86399/3600 rounds to 24 before crossing the day boundary
    [86400, "1d"],
    [172800, "2d"],
  ])("formats %d seconds as %s", (secs, out) => {
    expect(fmtAge(secs)).toBe(out);
  });
});

describe("fmtDurationMs", () => {
  it("returns em dash for null", () => {
    expect(fmtDurationMs(null)).toBe("—");
  });
  it("renders sub-second as rounded ms", () => {
    expect(fmtDurationMs(999)).toBe("999ms");
    expect(fmtDurationMs(0)).toBe("0ms");
  });
  it("renders >=1000ms as fixed-2 seconds", () => {
    expect(fmtDurationMs(1000)).toBe("1.00s");
    expect(fmtDurationMs(3500)).toBe("3.50s");
  });
});

describe("fmtConfidence", () => {
  it("returns em dash for null", () => {
    expect(fmtConfidence(null)).toBe("—");
  });
  it("fixes to 2 decimals", () => {
    expect(fmtConfidence(0.9)).toBe("0.90");
    expect(fmtConfidence(0.876)).toBe("0.88");
  });
});

describe("fmtTs", () => {
  it("returns em dash for null/empty", () => {
    expect(fmtTs(null)).toBe("—");
    expect(fmtTs("")).toBe("—");
  });
  it("returns the raw string when unparseable", () => {
    expect(fmtTs("not-a-date")).toBe("not-a-date");
  });
  it("formats a valid ISO timestamp to something other than the dash/raw", () => {
    const out = fmtTs("2026-01-01T00:00:00Z");
    expect(out).not.toBe("—");
    expect(out).not.toBe("2026-01-01T00:00:00Z");
    expect(out.length).toBeGreaterThan(0);
  });
});

describe("tickDuration", () => {
  it("is 'running' when there is no end", () => {
    expect(tickDuration("2026-01-01T00:00:00Z", null)).toBe("running");
  });
  it("is em dash when either timestamp is unparseable", () => {
    expect(tickDuration("nope", "2026-01-01T00:00:00Z")).toBe("—");
    expect(tickDuration("2026-01-01T00:00:00Z", "nope")).toBe("—");
  });
  it("formats the elapsed seconds with 2 decimals", () => {
    expect(tickDuration("2026-01-01T00:00:00Z", "2026-01-01T00:00:03Z")).toBe("3.00s");
    expect(tickDuration("2026-01-01T00:00:00Z", "2026-01-01T00:00:01.500Z")).toBe("1.50s");
  });
});
