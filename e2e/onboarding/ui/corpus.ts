// Reads the SAME source of truth as the API tier — `../fixtures.py --json` —
// rather than re-declaring the corpus, the identity prefix or the expected
// rows in TypeScript (the `subcategories/ui/corpus.ts` pattern).
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');

export interface CorpusJob {
  key: string;
  title: string;
  category: string;
  level: string;
  subcategories: string[] | null;
  location: string;
  company: string;
}

export interface AnswerSet {
  category: string[];
  subcategory: string[];
  level: string[];
  locations: string[];
  /** Question 4's company types (`[]` = any). */
  companyCategory: string[];
  /** The rows the Recent list must show — derived in fixtures.py, not by the app. */
  expectedKeys: string[];
}

interface Corpus {
  identityPrefix: string;
  emailPrefix: string;
  emailDomain: string;
  preexisting: { sub: string; email: string; stampedAt: string };
  headline: AnswerSet;
  /** The headline answers without question 4 (what an older backend keeps). */
  headlineNoCompanyType: AnswerSet;
  productManagerOnly: AnswerSet;
  everything: AnswerSet;
  jobs: CorpusJob[];
}

function load(): Corpus {
  const out = execFileSync(PYTHON, ['-m', 'e2e.onboarding.fixtures', '--json'], {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
  });
  return JSON.parse(out) as Corpus;
}

export const CORPUS = load();

export function job(key: string): CorpusJob {
  const found = CORPUS.jobs.find((j) => j.key === key);
  if (!found) throw new Error(`corpus.ts: no fixture job '${key}'`);
  return found;
}

export function titlesFor(keys: string[]): string[] {
  return keys.map((k) => job(k).title).sort();
}

/** Every title NOT in `keys` — the decoys a case must prove absent. */
export function decoyTitles(keys: string[]): string[] {
  return CORPUS.jobs.filter((j) => !keys.includes(j.key)).map((j) => j.title).sort();
}
