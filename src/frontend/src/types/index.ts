/**
 * Core type definitions for the Job Posting Analytics application
 */

/**
 * ATS provider type
 */
export type ATSProvider =
  | 'greenhouse'
  | 'lever'
  | 'ashby'
  | 'workday'
  | 'gem'
  | 'eightfold'
  | 'backend-scraper';

/**
 * Normalized job posting model.
 * All ATS-specific data is transformed into this structure.
 */
export interface Job {
  /** Unique identifier (from ATS) */
  id: string;

  /** ATS source system */
  source: ATSProvider;

  /** Company identifier (e.g., 'spacex', 'anthropic') */
  company: string;

  /** Job title */
  title: string;

  /** Department or division */
  department?: string;

  /** Team within department (if available) */
  team?: string;

  /** Location (city, state, country) */
  location?: string;

  /** Remote work indicator */
  isRemote?: boolean;

  /** Employment type (full-time, contract, intern, etc.) */
  employmentType?: string;

  /** Job creation/posting timestamp (ISO 8601) */
  createdAt: string;

  /** Direct link to job posting */
  url: string;

  /** Tags, keywords, or job families from ATS */
  tags?: string[];

  /** Original ATS response for debugging */
  raw: unknown;
}

/**
 * Supported time window options
 */
export type TimeWindow =
  | '30m'
  | '1h'
  | '3h'
  | '6h'
  | '12h'
  | '24h'
  | '3d'
  | '7d'
  | '14d'
  | '30d'
  | '90d'
  | '180d'
  | '1y'
  | '2y'
  | 'all';

/**
 * Time window display configuration
 */
export interface TimeWindowConfig {
  value: TimeWindow;
  label: string;
  durationMs: number;
  bucketSizeMs: number;
}

/**
 * Time bucket for graph data
 */
export interface TimeBucket {
  /** Bucket start time (ISO 8601) */
  bucketStart: string;

  /** Bucket end time (ISO 8601) */
  bucketEnd: string;

  /** Number of jobs in bucket */
  count: number;

  /** Job IDs in this bucket */
  jobIds: string[];
}

/**
 * Greenhouse-specific configuration
 */
export interface GreenhouseConfig {
  type: 'greenhouse';
  /** Board token or identifier */
  boardToken: string;
  /** Optional custom API base URL */
  apiBaseUrl?: string;
}

/**
 * Lever-specific configuration
 */
export interface LeverConfig {
  type: 'lever';
  /** Company identifier in Lever URL */
  companyId: string;
  /** Full jobs URL */
  jobsUrl: string;
  /** Optional custom API base URL */
  apiBaseUrl?: string;
}

/**
 * Ashby-specific configuration
 */
export interface AshbyConfig {
  type: 'ashby';
  /** Job board name from Ashby careers page URL */
  jobBoardName: string;
  /** Optional custom API base URL */
  apiBaseUrl?: string;
}

/**
 * Gem-specific configuration
 */
export interface GemConfig {
  type: 'gem';
  /** Vanity URL path (company slug on jobs.gem.com) */
  vanityUrlPath: string;
  /** Optional custom API base URL */
  apiBaseUrl?: string;
}

/**
 * Workday-specific configuration
 */
export interface WorkdayConfig {
  type: 'workday';
  /** Base URL for the Workday tenant (e.g., "https://nvidia.wd5.myworkdayjobs.com") */
  baseUrl: string;
  /** Tenant slug - path segment after /wday/cxs/ (e.g., "nvidia") */
  tenantSlug: string;
  /** Career site slug - path segment after tenant (e.g., "NVIDIAExternalCareerSite") */
  careerSiteSlug: string;
  /** Optional: Job detail base URL for constructing job links (e.g., "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details") */
  jobsUrl?: string;
  /** Optional: Override default page size for pagination (default: 50) */
  defaultPageSize?: number;
  /** Optional: Apply default filters to all requests */
  defaultFacets?: Record<string, string[]>;
  /** Optional custom API base URL for proxying */
  apiBaseUrl?: string;
}

/**
 * Eightfold AI-specific configuration
 *
 * Eightfold's public job board API requires:
 * - A tenant host (e.g., "explore.jobs.netflix.net")
 * - A domain scope (e.g., "netflix.com")
 * - Paginated requests (server caps page size at 10)
 */
export interface EightfoldConfig {
  type: 'eightfold';
  /**
   * Internal company identifier (matches `Company.id`). Used as the `company`
   * field on transformed `Job` objects so the `byCompany` cache key lines up.
   */
  companyId: string;
  /** Eightfold tenant host, e.g. "explore.jobs.netflix.net" (no protocol) */
  tenantHost: string;
  /** Domain query parameter Eightfold uses to scope jobs, e.g. "netflix.com" */
  domain: string;
  /** Optional override for pagination page size (server caps at 10) */
  defaultPageSize?: number;
  /** Optional custom API base URL (defaults to /api/eightfold) */
  apiBaseUrl?: string;
}

/**
 * Backend scraper configuration - for companies scraped via Python scripts
 */
export interface BackendScraperConfig {
  type: 'backend-scraper';
  /** Company identifier used in backend API (e.g., 'google', 'apple') */
  companyId: string;
  /** Optional custom API base URL for proxying */
  apiBaseUrl?: string;
}

/**
 * Company configuration for multi-ATS support
 */
export interface Company {
  /** Unique company identifier */
  id: string;

  /** Display name */
  name: string;

  /** ATS provider */
  ats: ATSProvider;

  /** ATS-specific configuration */
  config:
    | GreenhouseConfig
    | LeverConfig
    | AshbyConfig
    | GemConfig
    | WorkdayConfig
    | EightfoldConfig
    | BackendScraperConfig;

  /** Optional URL to company's job postings website */
  jobsUrl?: string;

  /** Optional URL to find recruiters on LinkedIn */
  recruiterLinkedInUrl?: string;
}

/**
 * Search tag with include/exclude mode
 */
export type SearchTag = {
  text: string;
  mode: 'include' | 'exclude';
};

/**
 * Graph filter state
 */
export interface GraphFilters {
  timeWindow: TimeWindow;
  searchTags?: SearchTag[];
  location?: string[];
  department?: string[];
  employmentType?: string;
  softwareOnly: boolean;
}

/**
 * List filter state (independent from graph)
 */
export interface ListFilters {
  timeWindow: TimeWindow;
  searchTags?: SearchTag[];
  location?: string[];
  department?: string[];
  employmentType?: string;
  softwareOnly: boolean;
}

/**
 * Recent jobs filter state (for all-companies view)
 * Subset of GraphFilters/ListFilters without department
 */
export interface RecentJobsFilters {
  timeWindow: TimeWindow;
  searchTags?: SearchTag[];
  location?: string[];
  employmentType?: string;
  softwareOnly: boolean;
  company?: string[];
}

/**
 * Company fetch progress status
 */
export type CompanyFetchStatus = 'pending' | 'loading' | 'success' | 'error';

/**
 * Progress tracking for individual company fetch
 */
export interface CompanyFetchProgress {
  /** Company identifier */
  companyId: string;

  /** Current fetch status */
  status: CompanyFetchStatus;

  /** Timestamp when fetch completed (ISO 8601) */
  completedAt?: string;

  /** Error message if fetch failed */
  error?: string;

  /** Number of jobs fetched (only for successful fetches) */
  jobCount?: number;
}

/**
 * Progress metadata for getAllJobs query
 */
export interface FetchProgress {
  /** Number of companies that have completed (success or error) */
  completed: number;

  /** Total number of companies to fetch */
  total: number;

  /** Per-company progress tracking */
  companies: CompanyFetchProgress[];
}
