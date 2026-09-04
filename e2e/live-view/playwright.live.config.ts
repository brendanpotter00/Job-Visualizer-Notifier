// `--live` only. A separate testDir (`ui-live/`) rather than a tag, so the spec that
// spends money cannot be picked up by the default, deterministic run.
import path from 'node:path';
import { baseConfig } from '../shared/playwright/playwright.config';

const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, 'artifacts', 'local');

export default baseConfig(path.join(__dirname, 'ui-live'), path.join(ARTIFACTS_DIR, 'ui-live'));
