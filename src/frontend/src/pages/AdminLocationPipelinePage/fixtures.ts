/**
 * Canned example traces for the Location Pipeline visualizer.
 *
 * This page is a *read-only explainer*: it never calls the backend. Every value
 * below is hand-authored to mirror the real two-tier normalization pipeline
 * (Tier-1 alias cache + Tier-2 Claude Haiku 4.5) shipped in PR #145 (`b8830a2`)
 * and the post-LLM canonicalization added in PR #149 (`8d2c9c6`). The example
 * strings/outputs are representative of the real golden set
 * (`src/backend/api/eval/golden_set.py`, `eval-baseline.json`).
 */

export type StageId = 'raw' | 'normalize' | 'tier1' | 'llm' | 'floor' | 'canonicalize' | 'persist';

/** Which control path an example takes through the seven stages. */
export type Branch = 'miss' | 'hit' | 'fail' | 'nokey';

export interface StageMeta {
  id: StageId;
  /** Short title shown in the node. */
  title: string;
  /** One-line subtitle (kept terse to fit the node). */
  subtitle: string;
  /** The backing code reference, shown in the detail panel. */
  codeRef: string;
}

/** Ordered list of the seven pipeline stages, mapped to real code. */
export const STAGES: StageMeta[] = [
  { id: 'raw', title: 'Raw string', subtitle: 'job_listings.location', codeRef: 'scraper output' },
  {
    id: 'normalize',
    title: 'normalize_string',
    subtitle: 'lowercase · NFKC',
    codeRef: 'location_normalization.py → normalize_string()',
  },
  {
    id: 'tier1',
    title: 'Tier-1 cache',
    subtitle: 'lookup_alias()',
    codeRef: 'location_normalization.py → lookup_alias()',
  },
  {
    id: 'llm',
    title: 'Tier-2 Haiku 4.5',
    subtitle: 'claude-haiku-4-5',
    codeRef: 'llm_client.py → normalize_location_via_llm()',
  },
  {
    id: 'floor',
    title: 'Confidence ≥ 0.5',
    subtitle: 'CONFIDENCE_FLOOR',
    codeRef: 'tasks/normalize_location.py',
  },
  {
    id: 'canonicalize',
    title: 'Canonicalize',
    subtitle: 'ISO-2 · USPS',
    codeRef: 'location_canonicalize.py → canonicalize()',
  },
  {
    id: 'persist',
    title: 'Persist',
    subtitle: '4 tables · done',
    codeRef: 'location_normalization.py → persist_llm_result()',
  },
];

/**
 * The ordered stage indices each branch visits. The visualizer steps through
 * this path; stages not in the path render dimmed (skipped).
 *  - miss : full pipeline
 *  - hit  : Tier-1 hit jumps straight to persist (no LLM spend)
 *  - fail : stops at the confidence floor (status = failed)
 *  - nokey: stops at the LLM stage (no API key → status left NULL)
 */
export const PATHS: Record<Branch, number[]> = {
  miss: [0, 1, 2, 3, 4, 5, 6],
  hit: [0, 1, 2, 6],
  fail: [0, 1, 2, 3, 4],
  nokey: [0, 1, 2, 3],
};

export interface StageIO {
  /** Input representation for the stage (optional for skipped stages). */
  in?: string;
  /** Output representation for the stage. */
  out: string;
}

/** Rows the example writes into each of the four tables on persist. */
export interface DbRows {
  locations: string[];
  locationAliases: string[];
  aliasLocations: string[];
  jobLocations: string[];
}

export interface PipelineExample {
  id: string;
  /** Label shown in the example picker. */
  label: string;
  /** The raw scraped location string. */
  raw: string;
  branch: Branch;
  /** Short note explaining the terminal outcome. */
  resultNote: string;
  /** Per-stage input/output payloads. */
  io: Record<StageId, StageIO>;
  /** Rows produced on persist (empty for failed / no-key examples). */
  rows: DbRows;
}

const EMPTY_ROWS: DbRows = {
  locations: [],
  locationAliases: [],
  aliasLocations: [],
  jobLocations: [],
};

export const EXAMPLES: PipelineExample[] = [
  {
    id: 'multi-miss',
    label: 'Multi-location · cache MISS',
    raw: 'Austin, TX, USA; Atlanta, GA, USA',
    branch: 'miss',
    resultNote: 'Two cities → two canonical rows; position 0 is the primary location.',
    io: {
      raw: { in: '"Austin, TX, USA; Atlanta, GA, USA"', out: 'verbatim scraped string' },
      normalize: {
        in: '"Austin, TX, USA; Atlanta, GA, USA"',
        out: '"austin, tx, usa; atlanta, ga, usa"',
      },
      tier1: {
        in: 'normalized cache key',
        out: 'MISS — no alias row → release connection, call Tier-2',
      },
      llm: {
        in: 'raw string → Haiku',
        out: '[\n  { kind: "city", city: "Austin",  region: "TX", country: "USA", confidence: 0.97 },\n  { kind: "city", city: "Atlanta", region: "GA", country: "USA", confidence: 0.96 }\n]',
      },
      floor: { in: 'max(confidence) = 0.97', out: '0.97 ≥ 0.50  ✓ pass' },
      canonicalize: {
        in: 'country "USA" → "US"; US region kept',
        out: '[\n  { canonical_name: "Austin, TX, US",  country: "US", region: "TX" },\n  { canonical_name: "Atlanta, GA, US", country: "US", region: "GA" }\n]',
      },
      persist: { in: '2 canonical locations', out: 'upsert rows · status → done' },
    },
    rows: {
      locations: ['Austin, TX, US', 'Atlanta, GA, US'],
      locationAliases: ["'austin, tx, usa; …'  src=llm  conf=0.97"],
      aliasLocations: ['pos 0 → Austin, TX, US', 'pos 1 → Atlanta, GA, US'],
      jobLocations: ['primary → Austin, TX, US', 'Atlanta, GA, US'],
    },
  },
  {
    id: 'cache-hit',
    label: 'Repeat string · cache HIT',
    raw: 'San Francisco, CA',
    branch: 'hit',
    resultNote: 'Already in the alias cache — Tier-2 is skipped, so there is zero LLM spend.',
    io: {
      raw: { in: '"San Francisco, CA"', out: 'verbatim scraped string' },
      normalize: { in: '"San Francisco, CA"', out: '"san francisco, ca"' },
      tier1: {
        in: 'normalized cache key',
        out: 'HIT → [location_id 42] · skip Tier-2, go straight to persist',
      },
      llm: { out: 'skipped (cache hit — no LLM call)' },
      floor: { out: 'skipped' },
      canonicalize: { out: 'skipped (already canonical in cache)' },
      persist: { in: 'location_id 42', out: 'link job_locations · status → done' },
    },
    rows: {
      locations: ['(exists) San Francisco, CA, US'],
      locationAliases: ["'san francisco, ca'  src=llm  (cached)"],
      aliasLocations: ['pos 0 → San Francisco, CA, US'],
      jobLocations: ['primary → San Francisco, CA, US'],
    },
  },
  {
    id: 'remote-eu',
    label: 'Remote · scoped EU',
    raw: 'Remote - EU',
    branch: 'miss',
    resultNote: 'kind = remote, remote_scope = eu, no city — a distinct row from Remote (US).',
    io: {
      raw: { in: '"Remote - EU"', out: 'verbatim scraped string' },
      normalize: { in: '"Remote - EU"', out: '"remote - eu"' },
      tier1: { in: 'normalized cache key', out: 'MISS → call Tier-2' },
      llm: {
        in: 'raw string → Haiku',
        out: '[\n  { kind: "remote", city: null, remote_scope: "eu", confidence: 0.94 }\n]',
      },
      floor: { in: 'max(confidence) = 0.94', out: '0.94 ≥ 0.50  ✓ pass' },
      canonicalize: {
        in: 'remote, scope "eu"',
        out: '[{ canonical_name: "Remote (EU)", kind: "remote", remote_scope: "eu" }]',
      },
      persist: { in: '1 remote location', out: 'upsert · status → done' },
    },
    rows: {
      locations: ['Remote (EU)'],
      locationAliases: ["'remote - eu'  src=llm  conf=0.94"],
      aliasLocations: ['pos 0 → Remote (EU)'],
      jobLocations: ['primary → Remote (EU)'],
    },
  },
  {
    id: 'garbage-fail',
    label: 'Garbage → low confidence',
    raw: 'asdf qwer ???',
    branch: 'fail',
    resultNote: 'Below the 0.5 confidence floor — marked failed and NOT cached. No rows written.',
    io: {
      raw: { in: '"asdf qwer ???"', out: 'verbatim scraped string' },
      normalize: { in: '"asdf qwer ???"', out: '"asdf qwer ???"' },
      tier1: { in: 'normalized cache key', out: 'MISS → call Tier-2' },
      llm: {
        in: 'raw string → Haiku',
        out: '[{ kind: "city", city: "asdf", confidence: 0.22 }]',
      },
      floor: {
        in: 'max(confidence) = 0.22',
        out: '0.22 < 0.50  ✗ → status = failed, nothing cached',
      },
      canonicalize: { out: '— not reached' },
      persist: { out: '— not reached' },
    },
    rows: EMPTY_ROWS,
  },
  {
    id: 'no-key',
    label: 'No API key → degraded',
    raw: 'Berlin, Germany',
    branch: 'nokey',
    resultNote:
      'ANTHROPIC_API_KEY unset → the task no-ops and status stays NULL (no retry burn). scan_unnormalized re-queues it every 5 min; it auto-resolves once the key is set.',
    io: {
      raw: { in: '"Berlin, Germany"', out: 'verbatim scraped string' },
      normalize: { in: '"Berlin, Germany"', out: '"berlin, germany"' },
      tier1: { in: 'normalized cache key', out: 'MISS → would call Tier-2' },
      llm: {
        in: 'ANTHROPIC_API_KEY unset',
        out: 'skipped — task no-ops, status left NULL (the safety net retries later)',
      },
      floor: { out: '— not reached' },
      canonicalize: { out: '— not reached' },
      persist: { out: '— not reached' },
    },
    rows: EMPTY_ROWS,
  },
];
