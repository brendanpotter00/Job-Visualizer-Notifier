import type { Job, BackendScraperConfig } from '../types';

/**
 * Backend job details stored in JobListing.details JSON field
 * Contains structured data extracted from scraped job detail pages
 * Works for any backend-scraped company (Google, Apple, etc.)
 */
export interface BackendJobDetails {
  minimum_qualifications?: string;
  preferred_qualifications?: string;
  about_the_job?: string;
  responsibilities?: string;
  // The org/team the role sits in. Ashby, Gem, Eightfold and Workday all write
  // this key; the Google/Apple/Microsoft scrapers do not. Until now the
  // transformer read `experience_level` into `Job.department` instead, so the
  // UI's "Department" filter has been showing seniority and this key reached
  // no screen at all.
  //
  // `| null` because the list endpoint emits it from a nullable column via
  // `jsonb_build_object`, so "no department" arrives as an explicit `null` on
  // the wire rather than an absent key. The transformer collapses both to
  // `undefined`.
  department?: string | null;
  experience_level?: string;
  salary_range?: string;
  is_remote_eligible?: boolean;
  apply_url?: string;
}

/**
 * One normalized canonical location tag attached to a job.
 * Matches the FastAPI JobLocationResponse model (src/backend/api/models.py),
 * sourced from the `job_locations` join. A job carries 0..N of these.
 */
export interface BackendJobLocation {
  canonicalName: string; // e.g. "Austin, TX, US"
  kind: string; // 'city' | 'region' | 'country' | 'remote'
  city: string | null;
  region: string | null;
  country: string | null; // short code, e.g. "US"
  remoteScope: string | null;
  isPrimary: boolean;
}

/**
 * Backend JobListing entity structure
 * Matches the FastAPI JobListingResponse model (src/backend/api/models.py)
 * Used for all scraped companies (Google, Apple, etc.)
 */
export interface BackendJobListing {
  id: string;
  title: string;
  company: string;
  location: string | null; // raw scraped string (display fallback)
  /** Normalized canonical location tags; [] for unnormalized/failed jobs. */
  locations: BackendJobLocation[];
  url: string;
  sourceId: string;
  details: string; // JSON string containing BackendJobDetails
  createdAt: string; // ISO 8601
  postedOn: string | null;
  closedOn: string | null;
  status: string; // "OPEN" | "CLOSED"
  hasMatched: boolean;
  aiMetadata: string; // JSON string
  firstSeenAt: string; // ISO 8601
  lastSeenAt: string; // ISO 8601
  consecutiveMisses: number;
  detailsScraped: boolean;
  /**
   * Enrichment facets (job-enricher pipeline); null/[] until a job is
   * enriched. Optional (not just nullable) so pre-enrichment fixtures and any
   * cached responses without the fields stay assignable — the transformer
   * defaults every one of them.
   */
  category?: string | null;
  level?: string | null;
  /** Free-form enrichment skill tags (job_tags), distinct from ATS-derived Job.tags. */
  tags?: string[];
  enrichmentStatus?: string | null;
}

/**
 * Standard API client interface.
 * All ATS clients implement this interface.
 */
export interface JobAPIClient {
  /**
   * Fetch jobs for a company.
   * @param config - Company-specific configuration
   * @param options - Fetch options
   * @returns Normalized jobs array
   */
  fetchJobs(
    config: BackendScraperConfig,
    options?: FetchJobsOptions
  ): Promise<FetchJobsResult>;
}

export interface FetchJobsOptions {
  /** Filter to jobs created after this timestamp */
  since?: string;

  /** Maximum number of jobs to fetch */
  limit?: number;

  /** AbortSignal for request cancellation */
  signal?: AbortSignal;
}

export interface FetchJobsResult {
  jobs: Job[];
  metadata: {
    totalCount: number;
    fetchedAt: string;
  };
}

/**
 * One keyset-paginated page of the batched `/api/jobs?companies=…` endpoint.
 *
 * Note the row shape is unchanged — keyset paging is purely additive on top of
 * the existing bare-array body, so `BackendJobListing` needed no new fields.
 */
export interface JobsPage {
  /** Every row in the page, in server order (`first_seen_at` DESC in keyset mode). */
  jobs: Job[];
  /**
   * The same `Job` objects grouped by company. Contains an entry for every
   * requested company id, including ones with zero rows on this page.
   */
  byCompanyId: Record<string, FetchJobsResult>;
  /**
   * The `X-Next-Cursor` response header, or `null` at the end of the walk.
   * Its **absence is the only end-of-walk signal** — the backend emits it iff
   * the page came back full, so `null` here means "stop", never "retry".
   */
  nextCursor: string | null;
}

/**
 * API error types
 */
export class APIError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public atsProvider?: 'backend-scraper',
    public retryable: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
  }
}

export enum ATSConstants {
  BackendScraper = 'backend-scraper',
}
