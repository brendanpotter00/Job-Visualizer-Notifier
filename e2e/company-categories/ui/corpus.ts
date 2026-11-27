// Reads the SAME source of truth as the API tier, `../fixtures.py --json`,
// rather than re-declaring the corpus or the expected sets in TypeScript.
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const FIXTURES_PY = path.join(REPO_ROOT, 'e2e', 'company-categories', 'fixtures.py');

export interface CorpusJob {
  key: string;
  title: string;
  company: string;
  level: string;
  category: string;
}

interface Corpus {
  sourceId: string;
  decoyCompanyId: string;
  reader: { sub: string; email: string };
  /** The committed JSON's categories, in display order. */
  categories: { slug: string; label: string }[];
  jobs: CorpusJob[];
  /** Expected row keys, derived in fixtures.py, not by the app. */
  expected: {
    bigTech: string[];
    aiLabsOrFintech: string[];
    fintech: string[];
    all: string[];
  };
}

function load(): Corpus {
  const out = execFileSync(PYTHON, [FIXTURES_PY, '--json'], { cwd: REPO_ROOT, encoding: 'utf-8' });
  return JSON.parse(out) as Corpus;
}

export const CORPUS = load();

export function labelOf(slug: string): string {
  const found = CORPUS.categories.find((c) => c.slug === slug);
  if (!found) throw new Error(`corpus.ts: no company type '${slug}'`);
  return found.label;
}

export function titlesFor(keys: string[]): string[] {
  return keys
    .map((k) => {
      const job = CORPUS.jobs.find((j) => j.key === k);
      if (!job) throw new Error(`corpus.ts: no fixture job '${k}'`);
      return job.title;
    })
    .sort();
}

/** Union of expected key lists, deduped and sorted. */
export function union(...lists: string[][]): string[] {
  return [...new Set(lists.flat())].sort();
}
