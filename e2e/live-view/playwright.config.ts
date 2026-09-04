// Section config — extends the feature-agnostic base, same as `add-companies`.
//
// `retries: 0` is inherited and is the point: this gate measures a timeline, and a
// retry would turn a real flicker into "it passed the second time".
import path from 'node:path';
import { baseConfig } from '../shared/playwright/playwright.config';

const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, 'artifacts', 'local');

export default baseConfig(path.join(__dirname, 'ui'), path.join(ARTIFACTS_DIR, 'ui'));
