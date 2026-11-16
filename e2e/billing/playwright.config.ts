// Section config — extends the shared base (add-companies/PLAN.md §1 rule 2).
// `retries: 0` is inherited: a retry would hide a webhook that only sometimes arrives.
import path from 'node:path';
import { baseConfig } from '../shared/playwright/playwright.config';

const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, 'artifacts', 'local');

export default baseConfig(path.join(__dirname, 'ui'), path.join(ARTIFACTS_DIR, 'ui'));
