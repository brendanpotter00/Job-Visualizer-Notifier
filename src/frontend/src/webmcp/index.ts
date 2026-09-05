/**
 * WebMCP — the agent-driving tool surface for the e2e verification harness.
 *
 * Public surface (§2): the flag config, the single store-only registrar, and
 * the React bridge that captures router/auth for Tier-2/3 tools. Everything is
 * dead code unless `WEBMCP_CONFIG.isEnabled` (VITE_WEBMCP === '1').
 */
export { WEBMCP_CONFIG } from './config';
export type { WebMcpConfig } from './config';
export { registerWebMcpTools } from './register';
export { WebMcpBridge } from './bridge';
export type { ToolCtx, ToolResult, WebMcpToolDef } from './types';
