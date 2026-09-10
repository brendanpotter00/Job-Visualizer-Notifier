// verify-onesecondswe :: Playwright config
//
// Extends the e2e base config verbatim (chromium, serial, retain-on-failure,
// baseURL http://127.0.0.1:3201). testDir is THIS helpers dir, so the specs it picks up
// are doctor.spec.ts (@doctor), drive.spec.ts (@drive), live_view.spec.ts (@live-view)
// and name_search.spec.ts (@name-search). Run it from `e2e/` so Node resolves
// `e2e/node_modules/@playwright`:
//
//   cd <repo>/e2e && npx playwright test \
//     --config=<repo>/.claude/skills/verify-onesecondswe/helpers/verify.playwright.config.ts \
//     --grep '@drive'
import fs from 'node:fs';
import path from 'node:path';
import { baseConfig } from '../../../../e2e/shared/playwright/playwright.config';

// Playwright transpiles this config as CJS here (nearest package.json has no
// "type":"module"), so use the ambient CJS __dirname — the sibling specs
// (drive.spec.ts) do the same. Using fileURLToPath(import.meta.url) made
// Playwright's loader treat the transpiled output as ESM ("exports is not
// defined"); this location is CJS, so import.meta must not appear.
const SKILL_DIR = path.resolve(__dirname, '..');

// Point Playwright's own outputDir at the current run's artifacts dir (written by
// launch.sh), so failure traces land beside the evidence. The specs write their
// own screenshots/aria/meta via E2E_VERIFY_ARTIFACTS (see below).
function currentRunDir(): string {
  try {
    const runId = fs.readFileSync(path.join(SKILL_DIR, 'artifacts', '.current-run'), 'utf-8').trim();
    if (runId) return path.join(SKILL_DIR, 'artifacts', runId);
  } catch {
    /* no launch recorded — fall through to an ad-hoc dir */
  }
  return path.join(SKILL_DIR, 'artifacts', 'adhoc');
}

const RUN_DIR = currentRunDir();
// Specs read this to place their evidence.
process.env.E2E_VERIFY_ARTIFACTS = process.env.E2E_VERIFY_ARTIFACTS ?? RUN_DIR;

export default baseConfig(__dirname, path.join(RUN_DIR, 'playwright'));
