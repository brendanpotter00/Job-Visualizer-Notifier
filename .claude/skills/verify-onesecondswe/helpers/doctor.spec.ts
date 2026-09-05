// verify-onesecondswe :: Doctor spec (@doctor)
//
// The read-only shim probe: loads the SPA and asserts window.__webmcp__ exposes
// exactly the 14 tools RUN1-SPEC §1 defines. A short/missing list means
// VITE_WEBMCP did not reach the vite child — re-run launch.sh. No fixture needed
// (this is anonymous and touches no state), so it imports plain @playwright/test.
import { test, expect } from '@playwright/test';

const EXPECTED_TOOLS = [
  // Tier 1 — read
  'search_jobs',
  'list_filter_options',
  'list_companies',
  'search_locations',
  'get_job',
  'get_company_hiring_trend',
  // Tier 2 — drive the live page
  'apply_feed_filters',
  'reset_feed_filters',
  'open_job',
  // Tier 3 — personalize
  'request_sign_in',
  'set_enabled_companies',
  'save_filter_defaults',
  'upvote_feature',
  'submit_feedback',
].sort();

test('[@doctor] window.__webmcp__ exposes the 14 expected tools', async ({ page }) => {
  await page.goto('/');
  // The shim is installed synchronously by registerWebMcpTools(store) at startup,
  // but give the module graph a beat to evaluate before reading it.
  await page.waitForFunction(() => typeof window.__webmcp__?.list === 'function', null, {
    timeout: 15_000,
  });

  const names = (await page.evaluate(() =>
    window.__webmcp__!.list().map((t) => t.name),
  )).sort();

  expect(names, 'shim tool set drifted from RUN1-SPEC §1 (or VITE_WEBMCP is off)').toEqual(
    EXPECTED_TOOLS,
  );

  // Every descriptor is well-formed (name + inputSchema + annotations).
  const descriptors = await page.evaluate(() => window.__webmcp__!.list());
  for (const d of descriptors) {
    expect(typeof d.name).toBe('string');
    expect(d.inputSchema, `tool ${d.name} missing inputSchema`).toBeTruthy();
    expect(typeof d.annotations.readOnlyHint).toBe('boolean');
  }
});
