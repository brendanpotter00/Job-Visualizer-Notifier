import type { BackendJobListing } from '../../../api/types';
import { jobsApi } from '../../../features/jobs/jobsApi';
import type { SearchJobsBatchRequest } from '../../../features/jobs/searchJobsTypes';
import { TRIPTYCH_REQUESTS } from '../../../pages/LandingPage/sections/triptychJobs';
import type { createTestStore } from '../../../test/testUtils';
import type { Job } from '../../../types';

export const LANDING_NOW = Date.parse('2026-11-13T19:00:00Z');
export const SOFTWARE_ENGINEERING = 'software_engineering';

const HOUR = 3_600_000;

export interface LandingJobSpec {
  company: string;
  hoursAgo: number;
  level?: string | null;
  category?: string | null;
  title?: string;
}

export function makeLandingJob(n: number, spec: LandingJobSpec, now = LANDING_NOW): Job {
  const firstSeenAt = new Date(now - spec.hoursAgo * HOUR).toISOString();
  return {
    id: `landing-${spec.company}-${n}`,
    source: 'backend-scraper',
    company: spec.company,
    title: spec.title ?? `Software Engineer ${n}, ${spec.company}`,
    location: 'San Francisco, CA, US',
    locations: [],
    createdAt: firstSeenAt,
    firstSeenAt,
    url: `https://jobs.example.test/${spec.company}/${n}`,
    tags: [],
    category: spec.category === undefined ? SOFTWARE_ENGINEERING : spec.category,
    level: spec.level === undefined ? 'mid' : spec.level,
    subcategories: null,
    enrichmentTags: [],
    enrichmentStatus: 'enriched',
    raw: null,
  };
}

function buildJobs(specs: LandingJobSpec[], now: number): Job[] {
  return specs.map((spec, i) => makeLandingJob(i + 1, spec, now));
}

export function buildRichLandingJobs(now = LANDING_NOW): Job[] {
  return buildJobs(
    [
      { company: 'stripe', hoursAgo: 1.5, level: 'new_grad' },
      { company: 'figma', hoursAgo: 3, level: 'intern' },
      { company: 'anthropic', hoursAgo: 9, level: 'intern' },
      { company: 'openai', hoursAgo: 30, level: 'new_grad' },
      { company: 'spacex', hoursAgo: 60, level: 'intern' },
      { company: 'databricks', hoursAgo: 130, level: 'new_grad' },
      { company: 'anthropic', hoursAgo: 0.5 },
      { company: 'openai', hoursAgo: 1, level: 'senior' },
      { company: 'google', hoursAgo: 2 },
      { company: 'stripe', hoursAgo: 4, level: 'senior' },
      { company: 'spacex', hoursAgo: 6 },
      { company: 'apple', hoursAgo: 8 },
      { company: 'ramp', hoursAgo: 11 },
      { company: 'netflix', hoursAgo: 14, level: 'senior' },
      { company: 'databricks', hoursAgo: 17 },
      { company: 'microsoft', hoursAgo: 22 },
      { company: 'nvidia', hoursAgo: 40 },
      { company: 'adobe', hoursAgo: 70, level: 'senior' },
      { company: 'airbnb', hoursAgo: 100 },
      { company: 'spotify', hoursAgo: 150 },
      { company: 'stripe', hoursAgo: 0.25, category: 'product_manager', title: 'Product Manager' },
      { company: 'google', hoursAgo: 1.25, level: 'intern', category: 'data_scientist' },
      { company: 'apple', hoursAgo: 0.1, level: null, category: null },
    ],
    now
  );
}

export function buildHolidayLandingJobs(now = LANDING_NOW): Job[] {
  return buildJobs(
    [
      { company: 'anthropic', hoursAgo: 240, level: 'intern' },
      { company: 'stripe', hoursAgo: 960, level: 'new_grad' },
      { company: 'anthropic', hoursAgo: 2 },
      { company: 'openai', hoursAgo: 5 },
      { company: 'stripe', hoursAgo: 12 },
      { company: 'spacex', hoursAgo: 40 },
      { company: 'databricks', hoursAgo: 50 },
      { company: 'ramp', hoursAgo: 60 },
      { company: 'google', hoursAgo: 80 },
      { company: 'apple', hoursAgo: 100 },
      { company: 'netflix', hoursAgo: 140 },
      { company: 'microsoft', hoursAgo: 480 },
      { company: 'nvidia', hoursAgo: 490 },
      { company: 'adobe', hoursAgo: 500 },
    ],
    now
  );
}

export function toBackendRow(job: Job): BackendJobListing {
  return {
    id: job.id,
    title: job.title,
    company: job.company,
    location: job.location ?? null,
    locations: [],
    url: job.url,
    sourceId: 'greenhouse',
    details: '{}',
    createdAt: job.firstSeenAt,
    postedOn: null,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: job.firstSeenAt,
    lastSeenAt: job.firstSeenAt,
    consecutiveMisses: 0,
    detailsScraped: true,
    category: job.category ?? null,
    level: job.level ?? null,
    subcategories: null,
    tags: [],
    enrichmentStatus: 'enriched',
  };
}

export interface SimulatedSearch {
  category?: readonly string[];
  level?: readonly string[];
  companies?: readonly string[];
  since: number;
  limit: number;
}

export function simulateSearch(corpus: readonly Job[], search: SimulatedSearch): Job[] {
  const matches = (values: readonly string[] | undefined, value: string | null | undefined) =>
    values === undefined || values.length === 0 || (value != null && values.includes(value));
  return corpus
    .filter(
      (job) =>
        matches(search.category, job.category) &&
        matches(search.level, job.level) &&
        matches(search.companies, job.company) &&
        Date.parse(job.firstSeenAt) >= search.since
    )
    .sort((a, b) => Date.parse(b.firstSeenAt) - Date.parse(a.firstSeenAt))
    .slice(0, search.limit);
}

export function simulateBatchRequest(
  corpus: readonly Job[],
  request: SearchJobsBatchRequest,
  asOf: number
): Job[] {
  return simulateSearch(corpus, {
    category: request.category,
    level: request.level,
    companies: request.companies,
    since: asOf - request.maxAgeHours * HOUR,
    limit: request.limit,
  });
}

export function simulateSearchParams(corpus: readonly Job[], params: URLSearchParams): Job[] {
  return simulateSearch(corpus, {
    category: params.getAll('category'),
    level: params.getAll('level'),
    companies: params.getAll('company'),
    since: Date.parse(params.get('since') ?? ''),
    limit: Number(params.get('limit')),
  });
}

export const SEARCH_META = { filteredTotal: null, countLast24h: 0, countLast3h: 0 };

export async function seedLandingJobs(
  store: ReturnType<typeof createTestStore>,
  jobs: Job[],
  asOf: number
): Promise<void> {
  await store.dispatch(
    jobsApi.util.upsertQueryData('searchJobsBatch', TRIPTYCH_REQUESTS, { jobs, asOf })
  );
}
