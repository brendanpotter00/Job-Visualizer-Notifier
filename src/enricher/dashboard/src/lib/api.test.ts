import { describe, it, expect, vi } from "vitest";
import { fetchJobDetail, postKnob } from "./api";
import { mockFetch } from "../test/utils";

describe("postKnob", () => {
  it("POSTs JSON {key,value} to /api/knobs and returns the parsed snapshot", async () => {
    const snapshot = { snapshot: { classify_model: "haiku" } };
    const fetchFn = mockFetch({ "/api/knobs": { json: snapshot } });

    const out = await postKnob("classify_model", "haiku");

    expect(out).toEqual(snapshot);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/knobs");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toMatchObject({ "content-type": "application/json" });
    expect(JSON.parse(init?.body as string)).toEqual({
      key: "classify_model",
      value: "haiku",
    });
  });

  it("throws with the server's `detail` on a 400", async () => {
    mockFetch({ "/api/knobs": { ok: false, status: 400, json: { detail: "invalid model 'gpt'" } } });
    await expect(postKnob("classify_model", "gpt")).rejects.toThrow("invalid model 'gpt'");
  });

  it("falls back to the status code when the error body is not JSON", async () => {
    mockFetch({ "/api/knobs": { ok: false, status: 500, jsonThrows: true } });
    await expect(postKnob("classify_model", "x")).rejects.toThrow("500");
  });
});

describe("fetchJobDetail", () => {
  it("builds the source_id/job_listing_id query and returns the parsed body", async () => {
    const detail = { category: "software_engineering", clean_description: "build things" };
    const fetchFn = mockFetch({ "/api/job": { json: detail } });

    const out = await fetchJobDetail("greenhouse", "abc/123");

    expect(out).toEqual(detail);
    const url = String(fetchFn.mock.calls[0][0]);
    expect(url).toContain("/api/job?");
    expect(url).toContain("source_id=greenhouse");
    // URLSearchParams encodes the slash in the listing id
    expect(url).toContain("job_listing_id=abc%2F123");
  });

  it("throws the status code on a non-ok response", async () => {
    mockFetch({ "/api/job": { ok: false, status: 404, json: {} } });
    await expect(fetchJobDetail("x", "nope")).rejects.toThrow("404");
  });

  it("does not swallow an unexpected fetch rejection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    await expect(fetchJobDetail("x", "y")).rejects.toThrow("network down");
  });
});
