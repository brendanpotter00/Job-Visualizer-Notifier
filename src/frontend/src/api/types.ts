import type { Job, GreenhouseConfig, LeverConfig, AshbyConfig, WorkdayConfig } from '../types';

/**
 * Greenhouse job board API response
 * @see https://developers.greenhouse.io/job-board.html
 */
export interface GreenhouseJobResponse {
  id: number;
  title: string;
  absolute_url: string;
  location: {
    name: string;
  };
  departments: Array<{
    id: number;
    name: string;
  }>;
  offices: Array<{
    id: number;
    name: string;
    location: string;
  }>;
  updated_at: string; // ISO timestamp
  first_published?: string; // ISO timestamp - when job was first posted
  metadata?: Array<{
    id: number;
    name: string;
    value: string | string[] | null; // API can return string, array, or null
  }>;
}

export interface GreenhouseAPIResponse {
  jobs: GreenhouseJobResponse[];
}

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
 * Ashby job posting API response
 * @see https://developers.ashbyhq.com/docs/public-job-posting-api
 */
export interface AshbyJobResponse {
  id: string;
  title: string;
  jobUrl: string;
  applyUrl: string;
  publishedAt: string; // ISO 8601 timestamp
  location: string;
  secondaryLocations?: Array<{
    location: string;
    address: {
      postalAddress: {
        addressRegion?: string;
        addressCountry?: string;
        addressLocality?: string;
      };
    };
  }>;
  department?: string;
  team?: string;
  employmentType: string; // "FullTime", "PartTime", "Intern", "Contract", "Temporary"
  isRemote?: boolean;
  isListed: boolean;
  descriptionHtml: string;
  descriptionPlain: string;
  address?: {
    postalAddress?: {
      addressRegion?: string;
      addressCountry?: string;
      addressLocality?: string;
    };
  };
  compensation?: {
    compensationTierSummary?: string;
    scrapeableCompensationSalarySummary?: string;
    compensationTiers?: unknown[];
    summaryComponents?: unknown[];
  };
  shouldDisplayCompensationOnJobPostings?: boolean;
}

export interface AshbyAPIResponse {
  apiVersion?: string;
  jobs: AshbyJobResponse[];
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
    config: GreenhouseConfig | LeverConfig | AshbyConfig | WorkdayConfig,
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
    softwareCount: number;
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
    public atsProvider?: 'greenhouse' | 'lever' | 'ashby' | 'workday',
    public retryable: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
  }
}

export enum ATSConstants {
  Greenhouse = 'greenhouse',
  Workday = 'workday',
  Ashby = 'ashby',
  Lever = 'lever',
}
