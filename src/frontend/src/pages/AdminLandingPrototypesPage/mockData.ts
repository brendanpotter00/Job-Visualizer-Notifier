/**
 * Mock job data for the landing-page prototypes.
 *
 * Prototypes are frontend-only: nothing here fetches. Jobs use REAL company ids
 * from config/companies.ts so CompanyLogo resolves the committed PNG assets,
 * and real enrichment slugs so cards/chips render exactly like production.
 *
 * Factories take `now` explicitly so tests are deterministic; the module-load
 * constants give the page live-looking "posted 38 min ago" labels. Timestamps
 * drift as a long-lived tab ages — acceptable for prototypes.
 */
import type { Job, JobLocation } from '../../types';
import { COMPANIES } from '../../config/companies';
import type { LandingStats } from './types';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const SF: JobLocation = {
  canonicalName: 'San Francisco, CA, US',
  kind: 'city',
  city: 'San Francisco',
  region: 'CA',
  country: 'US',
  isPrimary: true,
};
const NYC: JobLocation = {
  canonicalName: 'New York, NY, US',
  kind: 'city',
  city: 'New York',
  region: 'NY',
  country: 'US',
  isPrimary: true,
};
const SEATTLE: JobLocation = {
  canonicalName: 'Seattle, WA, US',
  kind: 'city',
  city: 'Seattle',
  region: 'WA',
  country: 'US',
  isPrimary: true,
};
const AUSTIN: JobLocation = {
  canonicalName: 'Austin, TX, US',
  kind: 'city',
  city: 'Austin',
  region: 'TX',
  country: 'US',
  isPrimary: true,
};
const SANTA_CLARA: JobLocation = {
  canonicalName: 'Santa Clara, CA, US',
  kind: 'city',
  city: 'Santa Clara',
  region: 'CA',
  country: 'US',
  isPrimary: true,
};
const HAWTHORNE: JobLocation = {
  canonicalName: 'Hawthorne, CA, US',
  kind: 'city',
  city: 'Hawthorne',
  region: 'CA',
  country: 'US',
  isPrimary: true,
};
const REMOTE_US: JobLocation = {
  canonicalName: 'Remote (US)',
  kind: 'remote',
  country: 'US',
  remoteScope: 'country',
  isPrimary: true,
};

interface MockJobSpec {
  company: string;
  title: string;
  /** Offset back from `now`, in ms, for firstSeenAt. */
  agoMs: number;
  category: string;
  level: string;
  location: JobLocation;
  isRemote?: boolean;
  employmentType?: string;
  enrichmentTags?: string[];
}

function makeJob(spec: MockJobSpec, index: number, now: number): Job {
  const firstSeenAt = new Date(now - spec.agoMs).toISOString();
  return {
    id: `mock-${spec.company}-${index}`,
    source: 'backend-scraper',
    company: spec.company,
    title: spec.title,
    location: spec.location.canonicalName,
    locations: [spec.location],
    isRemote: spec.isRemote ?? spec.location.kind === 'remote',
    employmentType: spec.employmentType ?? 'Full-time',
    createdAt: firstSeenAt,
    firstSeenAt,
    url: `https://onesecondswe.dev/?mock=${spec.company}-${index}`,
    tags: [],
    category: spec.category,
    level: spec.level,
    enrichmentTags: spec.enrichmentTags ?? [],
    enrichmentStatus: 'done',
    raw: null,
  };
}

/**
 * Rich fixture (~20 jobs): a believable weekday spread — a handful under 3h,
 * more through 24h/48h, the rest inside 7 days. Ordering here is arbitrary;
 * consumers sort by firstSeenAt.
 *
 * Level mix is load-bearing for the fresh-jobs triptych: it carries three
 * fresh `intern` postings plus a `new_grad` one, so the early-career slot has a
 * real pool to flip through instead of a single lonely card.
 */
const RICH_SPECS: readonly MockJobSpec[] = [
  // < 3 hours
  { company: 'spacex', title: 'Software Engineer, Starlink Ground Software', agoMs: 38 * MINUTE, category: 'software_engineering', level: 'mid', location: HAWTHORNE, enrichmentTags: ['python', 'golang'] },
  { company: 'anthropic', title: 'Software Engineer, Product', agoMs: 74 * MINUTE, category: 'software_engineering', level: 'mid', location: SF, enrichmentTags: ['typescript', 'react'] },
  { company: 'stripe', title: 'New Grad Software Engineer', agoMs: 2 * HOUR + 5 * MINUTE, category: 'software_engineering', level: 'new_grad', location: SF, enrichmentTags: ['java', 'ruby'] },
  { company: 'openai', title: 'Software Engineer, Applied AI', agoMs: 2 * HOUR + 48 * MINUTE, category: 'software_engineering', level: 'senior', location: SF, enrichmentTags: ['python', 'distributed-systems'] },
  // 3 – 24 hours
  { company: 'nvidia', title: 'Software Engineering Intern, Summer 2027', agoMs: 4 * HOUR + 20 * MINUTE, category: 'software_engineering', level: 'intern', location: SANTA_CLARA, employmentType: 'Intern', enrichmentTags: ['c++', 'cuda'] },
  { company: 'google', title: 'Software Engineer III, Core Infrastructure', agoMs: 5 * HOUR, category: 'software_engineering', level: 'mid', location: SEATTLE, enrichmentTags: ['c++', 'kubernetes'] },
  { company: 'figma', title: 'Software Engineer Intern, Summer 2027', agoMs: 7 * HOUR, category: 'software_engineering', level: 'intern', location: SF, employmentType: 'Intern', enrichmentTags: ['typescript'] },
  { company: 'microsoft', title: 'Software Engineering Intern, Azure Core (Summer 2027)', agoMs: 9 * HOUR + 40 * MINUTE, category: 'software_engineering', level: 'intern', location: SEATTLE, employmentType: 'Intern', enrichmentTags: ['c#', 'distributed-systems'] },
  { company: 'databricks', title: 'Software Engineer, Query Engine', agoMs: 11 * HOUR, category: 'software_engineering', level: 'senior', location: SF, enrichmentTags: ['scala', 'spark'] },
  { company: 'discord', title: 'Product Manager, Growth', agoMs: 14 * HOUR, category: 'product_manager', level: 'mid', location: REMOTE_US, enrichmentTags: [] },
  { company: 'cloudflare', title: 'Systems Engineer, Edge Platform', agoMs: 17 * HOUR, category: 'software_engineering', level: 'mid', location: AUSTIN, enrichmentTags: ['rust', 'networking'] },
  { company: 'netflix', title: 'Senior Software Engineer, Playback Systems', agoMs: 21 * HOUR, category: 'software_engineering', level: 'senior', location: REMOTE_US, enrichmentTags: ['java', 'streaming'] },
  // 24 – 48 hours
  { company: 'apple', title: 'Software Engineer, Maps Routing', agoMs: DAY + 3 * HOUR, category: 'software_engineering', level: 'mid', location: SEATTLE, enrichmentTags: ['swift', 'c++'] },
  { company: 'xai', title: 'Member of Technical Staff, Inference', agoMs: DAY + 8 * HOUR, category: 'software_engineering', level: 'senior', location: SF, enrichmentTags: ['python', 'cuda'] },
  { company: 'robinhood', title: 'Data Scientist, Trust & Safety', agoMs: DAY + 13 * HOUR, category: 'data_scientist', level: 'senior', location: NYC, enrichmentTags: ['sql', 'python'] },
  { company: 'reddit', title: 'Entry Level Software Engineer, Ads Platform', agoMs: DAY + 19 * HOUR, category: 'software_engineering', level: 'entry', location: REMOTE_US, enrichmentTags: ['python', 'go'] },
  // 2 – 7 days
  { company: 'microsoft', title: 'Software Engineer II, Azure Compute', agoMs: 2 * DAY + 6 * HOUR, category: 'software_engineering', level: 'mid', location: SEATTLE, enrichmentTags: ['c#', 'azure'] },
  { company: 'palantir', title: 'Forward Deployed Software Engineer', agoMs: 3 * DAY, category: 'software_engineering', level: 'entry', location: NYC, enrichmentTags: ['java', 'typescript'] },
  { company: 'airbnb', title: 'Staff Software Engineer, Payments', agoMs: 3 * DAY + 12 * HOUR, category: 'software_engineering', level: 'senior_plus', location: REMOTE_US, enrichmentTags: ['java', 'kotlin'] },
  { company: 'waymo', title: 'Hardware Engineer, Sensor Integration', agoMs: 4 * DAY + 8 * HOUR, category: 'hardware_engineer', level: 'senior', location: SF, enrichmentTags: ['fpga'] },
  { company: 'snowflake', title: 'Engineering Manager, Storage', agoMs: 5 * DAY + 4 * HOUR, category: 'software_engineering', level: 'manager', location: AUSTIN, enrichmentTags: [] },
  { company: 'spotify', title: 'Growth Marketing Associate', agoMs: 6 * DAY + 2 * HOUR, category: 'growth', level: 'entry', location: NYC, enrichmentTags: [] },
];

/**
 * Sparse fixture (~6 jobs): the weekend reality — under 20 fresh junior-SWE
 * roles sitewide, only a couple inside 24h. Sections must degrade gracefully
 * against this (brief §8).
 */
const SPARSE_SPECS: readonly MockJobSpec[] = [
  { company: 'anthropic', title: 'Software Engineer, Reliability', agoMs: 2 * HOUR + 20 * MINUTE, category: 'software_engineering', level: 'mid', location: SF, enrichmentTags: ['python'] },
  { company: 'apple', title: 'Software Engineer, CloudKit', agoMs: 30 * HOUR, category: 'software_engineering', level: 'mid', location: SEATTLE, enrichmentTags: ['swift'] },
  { company: 'google', title: 'Software Engineer, Early Career', agoMs: 3 * DAY + 5 * HOUR, category: 'software_engineering', level: 'entry', location: SEATTLE, enrichmentTags: [] },
  { company: 'stripe', title: 'Backend Engineer, Billing', agoMs: 4 * DAY + 9 * HOUR, category: 'software_engineering', level: 'mid', location: REMOTE_US, enrichmentTags: ['ruby'] },
  { company: 'spacex', title: 'Software Engineer, Flight Software', agoMs: 5 * DAY + 11 * HOUR, category: 'software_engineering', level: 'mid', location: HAWTHORNE, enrichmentTags: ['c++'] },
  { company: 'netflix', title: 'Product Manager, Games', agoMs: 6 * DAY + 7 * HOUR, category: 'product_manager', level: 'senior', location: REMOTE_US, enrichmentTags: [] },
];

export function buildMockJobs(now: number): Job[] {
  return RICH_SPECS.map((spec, i) => makeJob(spec, i, now));
}

export function buildSparseMockJobs(now: number): Job[] {
  return SPARSE_SPECS.map((spec, i) => makeJob(spec, i, now));
}

/**
 * The single "now" the whole prototype page renders against — stamped once at
 * module load so every "posted X ago" label, ticker window, and activity stat
 * agrees with the fixtures (and no component calls Date.now() during render,
 * keeping react-hooks/purity honestly clean).
 */
export const MOCK_NOW = Date.now();
export const MOCK_JOBS: Job[] = buildMockJobs(MOCK_NOW);
export const MOCK_JOBS_SPARSE: Job[] = buildSparseMockJobs(MOCK_NOW);

/** Headline numbers; companiesTracked derives from the registry so it can't rot. */
export const MOCK_STATS: LandingStats = {
  totalOpenJobs: 29_500,
  companiesTracked: COMPANIES.length,
  medianMinutesToSurface: 45,
};
