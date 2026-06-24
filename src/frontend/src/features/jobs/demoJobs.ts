import type { Job, JobLocation } from '../../types';
import { getCompanyById } from '../../config/companies.ts';

/**
 * Demo dataset for the admin-only "Demo mode" toggle (see uiSlice `demoModeEnabled`).
 *
 * When demo mode is on, `selectAllJobsFromQuery` returns this array instead of the
 * live RTK Query data, so the Recent Job Postings page shows a curated set of fake
 * software-engineering listings from real, tracked companies. Because the swap happens
 * upstream of all filtering/sorting/metrics, every existing feature (time-window,
 * location, company and keyword filters, sorting, counts, logos, links) works on this
 * data unchanged.
 *
 * IMPORTANT — stable reference: `DEMO_JOBS` is computed ONCE at module load. The recent-jobs
 * selectors are memoized (reselect) and the list relies on a stable jobs reference; returning
 * a freshly-generated array per selector call would thrash the cache. Never wrap this in a
 * function that the selector calls on every invocation.
 *
 * All company ids below are real entries in `config/companies.ts` so `getCompanyById` resolves
 * names, logos, and careers links. All titles contain "Engineer"/"Developer" so they survive
 * the "Software Engineering" keyword filter (substring match in `matchesSearchTags`).
 */

/** Real, tracked company ids: a mix of big tech, AI labs, and startups. */
const DEMO_COMPANY_IDS: readonly string[] = [
  // Big tech
  'google',
  'microsoft',
  'apple',
  'nvidia',
  'netflix',
  'adobe',
  'spotify',
  'stripe',
  'airbnb',
  'databricks',
  'datadog',
  'cloudflare',
  'snowflake',
  'dropbox',
  'pinterest',
  'reddit',
  'doordashusa',
  'robinhood',
  'mongodb',
  'gitlab',
  // AI labs
  'openai',
  'anthropic',
  'xai',
  'cohere',
  'perplexity',
  'cursor',
  'cognition',
  'scaleai',
  // Startups
  'linear',
  'notion',
  'ramp',
  'vercel',
  'figma',
  'supabase',
];

/** Software-engineering titles only (all contain "Engineer"/"Developer"). */
const SE_TITLES: readonly string[] = [
  'Software Engineer',
  'Senior Software Engineer',
  'Staff Software Engineer',
  'Backend Engineer',
  'Senior Backend Engineer',
  'Frontend Engineer',
  'Full Stack Engineer',
  'Machine Learning Engineer',
  'Platform Engineer',
  'Infrastructure Engineer',
  'DevOps Engineer',
  'Site Reliability Engineer',
  'Distributed Systems Engineer',
  'Mobile Engineer',
  'Data Engineer',
  'Security Engineer',
  'Software Developer',
];

/** Fully-structured canonical location tags (mirrors the `JobLocation` shape). */
const DEMO_LOCATIONS: readonly JobLocation[] = [
  {
    canonicalName: 'San Francisco, CA, US',
    kind: 'city',
    city: 'San Francisco',
    region: 'CA',
    country: 'US',
    remoteScope: null,
    isPrimary: true,
  },
  {
    canonicalName: 'New York, NY, US',
    kind: 'city',
    city: 'New York',
    region: 'NY',
    country: 'US',
    remoteScope: null,
    isPrimary: true,
  },
  {
    canonicalName: 'Seattle, WA, US',
    kind: 'city',
    city: 'Seattle',
    region: 'WA',
    country: 'US',
    remoteScope: null,
    isPrimary: true,
  },
  {
    canonicalName: 'Austin, TX, US',
    kind: 'city',
    city: 'Austin',
    region: 'TX',
    country: 'US',
    remoteScope: null,
    isPrimary: true,
  },
  {
    canonicalName: 'Mountain View, CA, US',
    kind: 'city',
    city: 'Mountain View',
    region: 'CA',
    country: 'US',
    remoteScope: null,
    isPrimary: true,
  },
  {
    canonicalName: 'Los Angeles, CA, US',
    kind: 'city',
    city: 'Los Angeles',
    region: 'CA',
    country: 'US',
    remoteScope: null,
    isPrimary: true,
  },
  {
    canonicalName: 'London, GB',
    kind: 'city',
    city: 'London',
    region: null,
    country: 'GB',
    remoteScope: null,
    isPrimary: true,
  },
  {
    canonicalName: 'Remote (US)',
    kind: 'remote',
    city: null,
    region: null,
    country: 'US',
    remoteScope: 'US',
    isPrimary: true,
  },
];

const DEPARTMENTS: readonly string[] = [
  'Engineering',
  'Infrastructure',
  'Platform',
  'Machine Learning',
  'Product Engineering',
];

const LANGS: readonly string[] = ['TypeScript', 'Go', 'Python', 'Rust', 'Java', 'C++'];

/** Number of fake listings to generate. */
export const DEMO_JOB_COUNT = 100;

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;

/**
 * Captured once at module load so the generated array is a stable reference.
 * Timestamps are therefore anchored to page-load time (acceptable for a demo).
 */
const NOW = Date.now();

/**
 * Spread `createdAt` toward the very recent past so the page looks alive at the default
 * 3h window and the recency metrics (last 3h / last 24h) and wider windows all demo well:
 *   - indices 0–49  → within the last ~3 hours (kept comfortably under 3h)
 *   - indices 50–74 → ~3h to ~22h ago
 *   - indices 75–99 → ~1 day to ~6 days ago
 */
function demoCreatedAt(i: number): string {
  let offsetMs: number;
  if (i < 50) {
    offsetMs = (i * 3 + 1) * MINUTE_MS; // 1 … 148 min (< 3h)
  } else if (i < 75) {
    offsetMs = 3 * HOUR_MS + (i - 50) * 45 * MINUTE_MS; // 3h … ~21.75h
  } else {
    offsetMs = 24 * HOUR_MS + (i - 75) * 5 * HOUR_MS; // 24h … ~144h (6d)
  }
  return new Date(NOW - offsetMs).toISOString();
}

/**
 * ~100 valid `Job` objects built deterministically (index-based cycling, no randomness)
 * so the dataset is reproducible across reloads and assertable in tests.
 */
export const DEMO_JOBS: Job[] = Array.from({ length: DEMO_JOB_COUNT }, (_, i): Job => {
  const company = DEMO_COMPANY_IDS[i % DEMO_COMPANY_IDS.length];
  const title = SE_TITLES[(i * 7) % SE_TITLES.length];
  const tag = DEMO_LOCATIONS[(i * 3) % DEMO_LOCATIONS.length];
  const department = DEPARTMENTS[(i * 2) % DEPARTMENTS.length];
  const lang = LANGS[(i * 5) % LANGS.length];

  return {
    id: `demo-${i}`,
    source: 'backend-scraper',
    company,
    title,
    department,
    location: tag.canonicalName,
    locations: [tag],
    isRemote: tag.kind === 'remote',
    employmentType: 'Full-time',
    createdAt: demoCreatedAt(i),
    // Real careers page for the company so a card click lands somewhere sensible.
    url: getCompanyById(company)?.jobsUrl ?? 'https://www.linkedin.com/jobs/',
    tags: ['Engineering', lang],
    raw: {},
  };
});
