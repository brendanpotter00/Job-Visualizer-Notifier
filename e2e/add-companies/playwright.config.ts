// Section config — extends the feature-agnostic base (PLAN.md §1's
// convention: a section's own config, not a fork of the shared one).
import path from 'node:path';
import { baseConfig } from '../shared/playwright/playwright.config';

const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, 'artifacts', 'local');

export default baseConfig(path.join(__dirname, 'ui'), path.join(ARTIFACTS_DIR, 'ui'));
