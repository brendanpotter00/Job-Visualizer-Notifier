import { getLoginRef, getNavigateRef } from './refs';
import { tier1Read } from './tools/tier1Read';
import { tier2DriveUi } from './tools/tier2DriveUi';
import { tier3Auth } from './tools/tier3Auth';
import type {
  AppStore,
  ToolCtx,
  ToolResult,
  WebMcpShim,
  WebMcpToolDef,
} from './types';

/**
 * Wrap a tool's `execute` for the real WebMCP API, guaranteeing the MCP text
 * envelope. Our `execute` already returns a full `ToolResult` (the `ok`/`err`
 * helpers build `content`); this just backfills `content` from
 * `structuredContent` for defense in depth.
 */
function wrapForWebMcp(
  execute: (args: Record<string, unknown>) => Promise<ToolResult>
): (args: Record<string, unknown>) => Promise<ToolResult> {
  return async (args) => {
    const result = await execute(args);
    if (!result.content || result.content.length === 0) {
      return {
        ...result,
        content: [{ type: 'text', text: JSON.stringify(result.structuredContent) }],
      };
    }
    return result;
  };
}

/**
 * The single store-only entry (§2.1). Builds every tool over `ctx`, registers
 * them on the real `document.modelContext` when present (Chrome origin-trial
 * only; best-effort, never throws when absent), and ALWAYS installs the
 * `window.__webmcp__` shim the Playwright gate drives.
 *
 * Idempotent: a second call replaces the shim and re-registers, so React
 * StrictMode's double-invoke is harmless.
 */
export function registerWebMcpTools(store: AppStore): void {
  const ctx: ToolCtx = {
    store,
    getNavigate: getNavigateRef,
    getLogin: getLoginRef,
  };

  const tools: WebMcpToolDef[] = [...tier1Read(ctx), ...tier2DriveUi(ctx), ...tier3Auth(ctx)];

  // Real WebMCP registration — undefined in every dev/CI browser, so this is a
  // best-effort branch that must never surface to the app.
  const modelContext = document.modelContext;
  if (modelContext?.registerTool) {
    for (const tool of tools) {
      try {
        modelContext.registerTool({
          name: tool.name,
          description: tool.description,
          inputSchema: tool.inputSchema,
          annotations: tool.annotations,
          execute: wrapForWebMcp(tool.execute),
        });
      } catch (e) {
        // One tool's registration failing must not abort the rest.
        console.warn(`[webmcp] registerTool failed for ${tool.name}:`, e);
      }
    }
  }

  // The shim: the surface the gate drives via page.evaluate. `call` returns a
  // tool's raw structuredContent; it rejects only on an unknown tool name.
  const toolMap = new Map(tools.map((t) => [t.name, t] as const));
  const shim: WebMcpShim = {
    list() {
      return tools.map((t) => ({
        name: t.name,
        description: t.description,
        inputSchema: t.inputSchema,
        annotations: t.annotations,
      }));
    },
    async call(name, args) {
      const tool = toolMap.get(name);
      if (!tool) {
        throw {
          error: `Unknown WebMCP tool: ${name}`,
          available: tools.map((t) => t.name),
        };
      }
      const result = await tool.execute(args ?? {});
      return result.structuredContent;
    },
  };

  window.__webmcp__ = shim;
}
