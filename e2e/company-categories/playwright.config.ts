// Section config: extends the shared base (never a fork). The base reads
// E2E_FRONTEND_URL from the environment run.sh exports, so specs land on :3208.
import path from 'node:path';
import { baseConfig } from '../shared/playwright/playwright.config';

const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, 'artifacts', 'local');

export default baseConfig(path.join(__dirname, 'ui'), path.join(ARTIFACTS_DIR, 'ui'));
