import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { ThemeProvider } from "@mui/material";
import { vi } from "vitest";
import { makeTheme } from "../theme";

/** Render a panel inside the real MUI theme, like App.tsx does. */
export function renderWithTheme(ui: ReactElement) {
  return render(<ThemeProvider theme={makeTheme("dark")}>{ui}</ThemeProvider>);
}

interface MockResponse {
  ok?: boolean; // default true
  status?: number; // default 200
  json?: unknown; // parsed by res.json()
  jsonThrows?: boolean; // simulate a non-JSON body (res.json() rejects)
}

type Handler = MockResponse | ((url: string, init?: RequestInit) => MockResponse);

/**
 * Stub global fetch, routing by first substring match of the request URL. Each
 * route is a canned response or a function of (url, init) for body-dependent
 * behavior (e.g. POST /api/knobs echoing the new value). Auto-restored between
 * tests via `unstubGlobals: true`.
 */
export function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const key = Object.keys(routes).find((k) => url.includes(k));
    if (!key) throw new Error(`mockFetch: no route matches ${url}`);
    const entry = routes[key];
    const r = typeof entry === "function" ? entry(url, init) : entry;
    return {
      ok: r.ok ?? true,
      status: r.status ?? 200,
      json: async () => {
        if (r.jsonThrows) throw new SyntaxError("not json");
        return r.json;
      },
    } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
