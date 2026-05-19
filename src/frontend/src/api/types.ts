import type {
  Job,
  LeverConfig,
  GemConfig,
  WorkdayConfig,
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
 * Workday job posting from API response
 * NOTE: This is a preliminary structure - will be updated after investigating actual API response
 */
export interface WorkdayJobPosting {
  /** Job title */
  title: string;
  /** Relative path to job posting (combine with baseUrl for full URL) */
  externalPath?: string;
  /** Location text (may be "X Locations" for multiple) */
  locationsText?: string;
  /** Relative posting date (e.g., "Posted Today", "Posted Yesterday") */
  postedOn?: string;
  /** Array of metadata, first element is typically job requisition ID */
  bulletFields?: string[];
  /** Allow additional fields we haven't discovered yet */
  [key: string]: unknown;
}

/**
 * Workday facet value - represents a single selectable filter option
 */
export interface WorkdayFacetValue {
  /** Human-readable name (e.g., "United States", "Engineering") */
  descriptor: string;
  /** Opaque identifier used in appliedFacets (e.g., "2fcb99c455831013ea52fb338f2932d8") */
  id: string;
  /** Number of jobs matching this facet value */
  count: number;
}

/**
 * Workday facet - represents a filter category with available options
 */
export interface WorkdayFacet {
  /** Facet type identifier (e.g., "locationHierarchy1", "jobFamilyGroup") */
  facetParameter: string;
  /** Human-readable facet name (e.g., "Locations", "Job Category") */
  descriptor?: string;
  /** Available filter values for this facet */
  values: WorkdayFacetValue[];
}

/**
 * Workday jobs API response
 * @see https://[tenant].wd5.myworkdayjobs.com/wday/cxs/[tenant]/[careerSite]/jobs
 */
export interface WorkdayJobsResponse {
  /** Total number of matching jobs (used for pagination) */
  total: number;
  /** Array of job postings for current page */
  jobPostings: WorkdayJobPosting[];
  /** Available filters with counts (only present in first page response) */
  facets: WorkdayFacet[];
  /** Whether user is authenticated (always false for public API) */
  userAuthenticated: boolean;
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
      | WorkdayConfig
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
      | 'workday'
      | 'backend-scraper',
    public retryable: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
  }
}

export enum ATSConstants {
  Workday = 'workday',
  Gem = 'gem',
  Lever = 'lever',
  BackendScraper = 'backend-scraper',
}
