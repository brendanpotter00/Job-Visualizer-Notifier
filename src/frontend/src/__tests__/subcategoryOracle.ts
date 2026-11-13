import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

/**
 * THE CROSS-LANGUAGE ORACLE, read from the frontend side.
 *
 * `src/backend/api/tests/fixtures/subcategory_filter_oracle.json` is authored by
 * the backend (RA-4) and read by BOTH halves: the pytest half asserts the SQL
 * predicate returns the declared ids, and the vitest half asserts the client
 * matcher returns the same ones. One committed file with two readers is the only
 * mechanical way to assert the two languages agree — two hand-maintained lists
 * are exactly the thing that drifts.
 *
 * Located by walking UP from the runner's cwd to the first directory containing
 * `src/backend`, NOT off `import.meta.url`: vitest runs in the jsdom
 * environment, where `import.meta.url` is an http: URL and `fileURLToPath`
 * throws on it. Walking up is cwd-independent in the way that matters here — it
 * resolves from the repo root and from `src/frontend` alike.
 */

export interface OracleJob {
  job_id: string;
  enrichment_category: string;
  enrichment_subcategories: string[] | null;
}

export interface OracleSelection {
  name: string;
  subcategory: string[];
  expected: string[];
}

export interface OracleComposition {
  name: string;
  category: string[];
  subcategory: string[];
  expected: string[];
}

export interface SubcategoryOracle {
  expansion: Record<string, string[]>;
  source_id: string;
  jobs: OracleJob[];
  selections: OracleSelection[];
  category_composition: OracleComposition[];
}

const RELATIVE_PATH = join(
  'src',
  'backend',
  'api',
  'tests',
  'fixtures',
  'subcategory_filter_oracle.json'
);

export function findOraclePath(): string {
  let dir = resolve(process.cwd());
  for (let i = 0; i < 8; i += 1) {
    const candidate = join(dir, RELATIVE_PATH);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(
    `could not find ${RELATIVE_PATH} walking up from ${process.cwd()} — the ` +
      'committed cross-language oracle fixture is missing or moved'
  );
}

export function loadSubcategoryOracle(): SubcategoryOracle {
  return JSON.parse(readFileSync(findOraclePath(), 'utf8')) as SubcategoryOracle;
}
