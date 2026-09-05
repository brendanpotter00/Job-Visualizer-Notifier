import type { JSONSchema7 } from 'json-schema';
import type { NavigateFunction } from 'react-router-dom';
import type { store } from '../app/store';

/**
 * The app's configured Redux store (value type). `registerWebMcpTools` takes
 * exactly this — the single store-only entry the contract mandates.
 */
export type AppStore = typeof store;

/** Router navigate fn, captured out of band by the bridge (§2.5). */
export type NavigateFn = NavigateFunction;

/** Auth login trigger (`useAuth().login`), captured by the bridge. */
export type LoginFn = () => Promise<void>;

/**
 * MCP tool-call result envelope.
 *
 * `execute` returns this fully-formed: `structuredContent` is the raw object a
 * tool produces, and `content` is its JSON-stringified text form (built by the
 * `ok`/`err` helpers in `tools/shared.ts`). The real-WebMCP wrapper passes it
 * through; the `window.__webmcp__` shim hands `structuredContent` straight back
 * to Playwright so `page.evaluate` gets clean JSON.
 */
export interface ToolResult {
  content: Array<{ type: 'text'; text: string }>;
  structuredContent: unknown;
  isError?: boolean;
}

/**
 * One WebMCP tool. `execute` receives args already shaped by the caller against
 * `inputSchema`; every tool re-parses defensively (the shim does not run a JSON
 * Schema validator).
 */
export interface WebMcpToolDef {
  name: string;
  /** Agent-facing, one sentence: says WHAT it does and WHAT it returns. */
  description: string;
  /** draft-07 object schema; `additionalProperties:false`. */
  inputSchema: JSONSchema7;
  annotations: { readOnlyHint: boolean; openWorldHint?: boolean };
  execute(args: Record<string, unknown>): Promise<ToolResult>;
}

/**
 * Context threaded into every tool factory. `store` is passed at registration;
 * `getNavigate`/`getLogin` read the module refs the bridge fills, so Tier-2/3
 * tools reach the real router/auth at call time even though registration is
 * store-only.
 */
export interface ToolCtx {
  store: AppStore;
  getNavigate(): NavigateFn | null;
  getLogin(): LoginFn | null;
}

/** Descriptor the shim's `list()` returns — schema surface, no `execute`. */
export interface WebMcpToolDescriptor {
  name: string;
  description: string;
  inputSchema: JSONSchema7;
  annotations: { readOnlyHint: boolean; openWorldHint?: boolean };
}

/**
 * The `window.__webmcp__` shim surface Playwright drives via `page.evaluate`.
 * `call` resolves with a tool's raw `structuredContent`; it rejects only on a
 * malformed call (unknown tool name), never on a tool-level error (those come
 * back as `structuredContent` carrying an `error` field).
 */
export interface WebMcpShim {
  list(): WebMcpToolDescriptor[];
  call(name: string, args?: Record<string, unknown>): Promise<unknown>;
}

/**
 * Minimal shape of the real (Chrome origin-trial) WebMCP registration surface.
 * `document.modelContext` is `undefined` in every dev/CI browser, so this is
 * consumed best-effort and must never be assumed present.
 */
export interface ModelContextTool {
  name: string;
  description: string;
  inputSchema: JSONSchema7;
  annotations: { readOnlyHint: boolean; openWorldHint?: boolean };
  execute(args: Record<string, unknown>): Promise<ToolResult>;
}

export interface ModelContext {
  registerTool?(tool: ModelContextTool): void;
}

declare global {
  interface Document {
    modelContext?: ModelContext;
  }
  interface Window {
    __webmcp__?: WebMcpShim;
  }
}
