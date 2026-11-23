// Section config — extends the shared base (add-companies/PLAN.md §1 rule 2).
// The base reads E2E_FRONTEND_URL from the environment run.sh exports, so these
// specs land on :3205.
//
// `retries: 0` is inherited and is the point: "the questions never appear" is
// exactly the assertion a retry would turn into "they did not appear the
// second time".
import path from 'node:path';
import { baseConfig } from '../shared/playwright/playwright.config';

const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, 'artifacts', 'local');

export default baseConfig(path.join(__dirname, 'ui'), path.join(ARTIFACTS_DIR, 'ui'));
