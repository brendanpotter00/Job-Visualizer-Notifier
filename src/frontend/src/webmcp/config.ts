/**
 * Feature-flag config for the WebMCP tool surface.
 *
 * CLIENT-side only. Default OFF — with `VITE_WEBMCP` unset the app is
 * byte-for-byte what shipped before this module existed: no tool registration,
 * no bridge mount, no `window.__webmcp__` shim, and zero runtime cost beyond a
 * dead import branch. Turned on only by the e2e verification harness (which
 * exports `VITE_WEBMCP=1` before `vite dev`), never in production.
 */
export interface WebMcpConfig {
  /** True only when `VITE_WEBMCP` is exactly the string `'1'`. */
  isEnabled: boolean;
}

export const WEBMCP_CONFIG: WebMcpConfig = {
  // Strict `=== '1'` (not truthiness) so a stray `0`, `false`, or an
  // accidentally-set-but-empty var can never switch the surface on.
  isEnabled: import.meta.env.VITE_WEBMCP === '1',
};
