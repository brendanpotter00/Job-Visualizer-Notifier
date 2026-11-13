// Section config — extends the feature-agnostic base, same as `add-companies`
// and `live-view` (PLAN.md §1's convention: a section's own config, never a
// fork of the shared one).
//
// The base config reads `E2E_FRONTEND_URL` / `E2E_FRONTEND_PORT` from the
// environment `run.sh` exports, so this section's specs land on :3203 while
// the other two stay on :3201 with no change to either.
//
// `retries: 0` is inherited and is the point: a filter either returns the
// right set or it does not, and a retry would turn a real ordering or
// debounce defect into "it passed the second time".
import path from 'node:path';
import { baseConfig } from '../shared/playwright/playwright.config';

const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, 'artifacts', 'local');

export default baseConfig(path.join(__dirname, 'ui'), path.join(ARTIFACTS_DIR, 'ui'));
