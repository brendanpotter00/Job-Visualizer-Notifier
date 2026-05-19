import type {
  Job,
  LeverConfig,
  GemConfig,
  EightfoldConfig,
  BackendScraperConfig,
} from '../types';

/**
 * Lever job posting API response
 * @see https://github.com/lever/postings-api
 */
export interface LeverJobResponse {
  id: string;
  text: string; // Job title
  hostedUrl: string;
  categories: {
    commitment?: string; // Full-time, Part-time, etc.
    department?: string;
    location?: string;
    team?: string;
  };
  createdAt: number; // Unix timestamp (milliseconds)
  tags?: (string | string[] | null)[]; // API can return mixed types
  workplaceType?: 'remote' | 'onsite' | 'unspecified';
}

/**
 * Gem job board API response
 * @see https://api.gem.com/job_board/v0/reference
 */
export interface GemJobResponse {
  id: string;
  title: string;
  absolute_url: string;
  content: string;
  content_plain: string;
  created_at: string;
  updated_at: string;
  first_published_at: string | null;
  employment_type: string | null;
  location_type: string | null;
  location: { name: string } | null;
  departments: Array<{ id: string; name: string }>;
  offices: Array<{ id: string; name: string; location?: { name: string } }>;
  internal_job_id: string;
  requisition_id: string;
}

/**
 * Eightfold AI public jobs API — single position entry
 *
 * Observed live on 2026-04-18 from GET https://explore.jobs.netflix.net/api/apply/v2/jobs
 * Endpoint is undocumented; schema intentionally permissive via index signature.
 */
export interface EightfoldJobPosition {
  /** Numeric position id */
  id: number;
  /** Job title */
  name: string;
  /** Comma-delimited location (e.g., "Los Angeles,California,United States of America") */
  location?: string;
  /** Array of locations (rarely multiple) */
  locations?: string[];
  /** Department (nullable) */
  department?: string | null;
  /** Business unit (nullable) */
  business_unit?: string | null;
  /** Unix epoch seconds — last update time */
  t_update?: number;
  /** Unix epoch seconds — original posting creation time */
  t_create?: number;
  /** ATS requisition id (e.g., "JR40083") */
  ats_job_id?: string;
  /** Display requisition id (usually equal to ats_job_id) */
  display_job_id?: string;
  /** Always "ATS" for standard positions */
  type?: string;
  /** Job description HTML (often empty on list endpoint) */
  job_description?: string;
  /** "onsite" | "remote" | "hybrid" | null */
  work_location_option?: 'onsite' | 'remote' | 'hybrid' | null;
  /** Canonical URL to the job posting */
  canonicalPositionUrl?: string;
  /** If true, position is not publicly listed and should be filtered out */
  isPrivate?: boolean;
  /** Allow other undocumented fields */
  [key: string]: unknown;
}

/**
 * Eightfold AI public jobs API response
 * @see https://explore.jobs.netflix.net/api/apply/v2/jobs
 */
export interface EightfoldAPIResponse {
  /** Domain scope (echo of request param) */
  domain?: string;
  /** Positions page */
  positions: EightfoldJobPosition[];
  /** Total matching positions across all pages */
  count?: number;
  /** Allow other top-level fields (branding, facets, etc.) */
  [key: string]: unknown;
}

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
  experience_level?: string;
  salary_range?: string;
  is_remote_eligible?: boolean;
  apply_url?: string;
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
  location: string | null;
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
    config:
      | LeverConfig
      | GemConfig
      | EightfoldConfig
      | BackendScraperConfig,
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
 * API error types
 */
export class APIError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public atsProvider?:
      | 'lever'
      | 'gem'
      | 'eightfold'
      | 'backend-scraper',
    public retryable: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
  }
}

export enum ATSConstants {
  Gem = 'gem',
  Lever = 'lever',
  Eightfold = 'eightfold',
  BackendScraper = 'backend-scraper',
}
