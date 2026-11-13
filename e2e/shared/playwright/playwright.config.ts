// Base Playwright config (PLAN.md §1). Section configs (e.g.
// add-companies/playwright.config.ts) import and extend this — nothing here
// names a board, a company, or a page.
import { defineConfig, devices } from '@playwright/test';

// The section's own frontend, from the environment its run.sh exports.
// Defaults to the port `add-companies` and `live-view` share.
export const FRONTEND_BASE_URL =
  process.env.E2E_FRONTEND_URL ?? `http://127.0.0.1:${process.env.E2E_FRONTEND_PORT ?? 3201}`;

/**
 * Trace/video/screenshot policy: retain evidence ONLY on failure (PLAN.md
 * §10 — "a green run leaves summary.md and the two stack logs and nothing
 * else"). A passing suite must not accumulate megabytes of traces nobody
 * reads.
 */
export function baseConfig(testDir: string, outputDir: string) {
  return defineConfig({
    testDir,
    outputDir,
    timeout: 5 * 60_000,
    expect: { timeout: 15_000 },
    fullyParallel: false,
    forbidOnly: !!process.env.CI,
    retries: 0,
    workers: 1,
    reporter: [['list'], ['json', { outputFile: `${outputDir}/playwright-report.json` }]],
    use: {
      baseURL: FRONTEND_BASE_URL,
      trace: 'retain-on-failure',
      screenshot: 'only-on-failure',
      video: 'off',
      actionTimeout: 15_000,
      navigationTimeout: 30_000,
    },
    projects: [
      {
        name: 'chromium',
        use: { ...devices['Desktop Chrome'] },
      },
    ],
  });
}
