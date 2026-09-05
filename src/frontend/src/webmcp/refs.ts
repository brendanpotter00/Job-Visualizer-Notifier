import type { LoginFn, NavigateFn } from './types';

/**
 * Module-level refs the WebMcpBridge fills with the live router `navigate` and
 * Auth0 `login`. Tier-2/3 tools read them at call time via `ctx.getNavigate()`
 * / `ctx.getLogin()`, which keeps `registerWebMcpTools(store)` store-only while
 * still driving the real router/auth. No React import here on purpose — the
 * refs are plain module state so the store-only tools can reach them.
 */
let navigateRef: NavigateFn | null = null;
let loginRef: LoginFn | null = null;

export function setNavigateRef(fn: NavigateFn | null): void {
  navigateRef = fn;
}

export function getNavigateRef(): NavigateFn | null {
  return navigateRef;
}

export function setLoginRef(fn: LoginFn | null): void {
  loginRef = fn;
}

export function getLoginRef(): LoginFn | null {
  return loginRef;
}
