// Reads the SAME source of truth as the API tier — `../fixtures.py` — rather
// than re-declaring the eleven rows in TypeScript. Exactly the trick
// `add-companies/ui/boards.ts` uses against `boards.py`, and for the same
// reason: two hand-maintained copies of a fixture table drift, and the drift
// shows up as a UI case asserting a title the seeder never wrote.
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const FIXTURES_PY = path.join(REPO_ROOT, 'e2e', 'subcategories', 'fixtures.py');

export interface CorpusJob {
  key: string;
  title: string;
  companyId: string;
  level: string;
  category: string;
  /** null = SQL NULL ("never evaluated"); [] = '{}' ("nothing applies"). */
  subcategories: string[] | null;
}

interface Corpus {
  sourceId: string;
  sweCategory: string;
  nonSweCategory: string;
  subcategorySlugs: string[];
  widening: Record<string, string[]>;
  companies: Array<{ id: string; displayName: string }>;
  jobs: CorpusJob[];
}

function load(): Corpus {
  const out = execFileSync(PYTHON, [FIXTURES_PY, '--json'], { encoding: 'utf-8' });
  return JSON.parse(out) as Corpus;
}

export const CORPUS = load();
export const JOBS = CORPUS.jobs;

export function job(key: string): CorpusJob {
  const found = JOBS.find((j) => j.key === key);
  if (!found) throw new Error(`corpus.ts: no fixture job '${key}'`);
  return found;
}

/** The titles the Recent list should render for a set of fixture keys. */
export function titlesFor(...keys: string[]): string[] {
  return keys.map((k) => job(k).title).sort();
}

/**
 * The titles a `?subcategory=<slug>` selection must produce, across BOTH
 * fixture companies — the Recent page has no company control, so every UI case
 * sees the whole corpus.
 *
 * Applies the widening from the fixture table, NOT from the code under test,
 * so SC-04's UI half is checking an independently derived answer.
 */
export function titlesForSubcategory(slug: string): string[] {
  const wanted = new Set(CORPUS.widening[slug] ?? [slug]);
  return JOBS.filter((j) => (j.subcategories ?? []).some((s) => wanted.has(s)))
    .map((j) => j.title)
    .sort();
}

/** Every SWE title, including the NULL and the '{}' row — SC-01's expected set. */
export function sweTitles(): string[] {
  return JOBS.filter((j) => j.category === CORPUS.sweCategory).map((j) => j.title).sort();
}

export function allTitles(): string[] {
  return JOBS.map((j) => j.title).sort();
}
