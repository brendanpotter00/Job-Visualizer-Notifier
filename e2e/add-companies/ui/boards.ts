// Reads the SAME source of truth as the API tier — `../boards.py` — rather
// than re-declaring board URLs in TypeScript (PLAN.md §1: "boards.py — the
// six board URLs + expected classification — ONE source of truth").
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const BOARDS_PY = path.join(REPO_ROOT, 'e2e', 'add-companies', 'boards.py');

export interface BoardEntry {
  caseId: string;
  label: string;
  url: string;
  path: string;
  expect: string | null;
  approxJobCount: number | null;
}

function loadBoards(): BoardEntry[] {
  const out = execFileSync(PYTHON, [BOARDS_PY, '--json'], { encoding: 'utf-8' });
  const raw = JSON.parse(out) as Array<{
    case_id: string;
    label: string;
    url: string;
    path: string;
    expect: string | null;
    approx_job_count: number | null;
  }>;
  return raw.map((b) => ({
    caseId: b.case_id,
    label: b.label,
    url: b.url,
    path: b.path,
    expect: b.expect,
    approxJobCount: b.approx_job_count,
  }));
}

const ALL_BOARDS = loadBoards();

function byLabel(label: string): BoardEntry {
  const found = ALL_BOARDS.find((b) => b.label === label);
  if (!found) throw new Error(`boards.ts: no board labeled '${label}'`);
  return found;
}

export const MICROSOFT = byLabel('Microsoft');
export const AMAZON = byLabel('Amazon');
export const CISCO = byLabel('Cisco');
export const ATLASSIAN = byLabel('Atlassian');
export const JANE_STREET = byLabel('Jane Street');
export const SPOTIFY = byLabel('Spotify');
