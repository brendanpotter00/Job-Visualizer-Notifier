/**
 * Core type definitions for the Job Posting Analytics application
 */

/**
 * ATS provider type
 */
export type ATSProvider = 'backend-scraper';

/**
 * A normalized canonical location tag attached to a job (city, region,
 * country, or remote). A job can carry several; the location filter treats
 * each as a tag so one "Austin, TX, US" option matches every job tagged with it.
 */
export interface JobLocation {
  /** Clean display label, e.g. "Austin, TX, US". */
  canonicalName: string;
  /** 'city' | 'region' | 'country' | 'remote'. */
  kind: string;
  city?: string | null;
  region?: string | null;
  /** Short country code, e.g. "US". */
  country?: string | null;
  remoteScope?: string | null;
  isPrimary: boolean;
}

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

  /** Raw location string from the ATS/scraper (used for free-text search and display fallback). */
  location?: string;

  /** Normalized canonical location tags (multi-location aware); used by the location filter. */
  locations?: JobLocation[];

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

  /**
   * Enrichment facets from the job-enricher pipeline (null/absent until a job
   * is enriched). `enrichmentTags` is deliberately separate from `tags`: the
   * latter is synthesized from ATS details (experience level / remote flag)
   * and already feeds free-text search.
   */
  category?: string | null;

  /** Level slug; filtering must honor the new_grad ⊂ entry hierarchy. */
  level?: string | null;

  /** Free-form enrichment skill tags (lowercase slugs). */
  enrichmentTags?: string[];

  /** NULL | 'claimed' | 'done' | 'needs_human'. */
  enrichmentStatus?: string | null;

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
  config: BackendScraperConfig;

  /** Optional URL to company's job postings website */
  jobsUrl?: string;

  /**
   * For companies whose `ats === 'backend-scraper'`, the ATS that originally
   * served their jobs before migration to the backend. Used by the Why page
   * to group migrated providers (Ashby, Greenhouse, Lever, Gem, Eightfold,
   * Workday) under their own column instead of lumping them with the true
   * Custom Web Scrapers (Google/Apple/Microsoft).
   */
  sourceAts?: 'ashby' | 'eightfold' | 'gem' | 'greenhouse' | 'lever' | 'workday';

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
 * A user-created (or built-in) named keyword list. Selecting a list on a filter
 * page replaces that page's `searchTags` with the list's `tags`.
 *
 * The built-in "Software Engineering (default)" list is synthesized by the
 * backend, returned last, carries `isBuiltin: true` (id `"builtin-swe"`), and is
 * read-only in the editor.
 */
export interface KeywordList {
  id: string;
  name: string;
  tags: SearchTag[];
  isBuiltin: boolean;
  position: number;
}

/**
 * Persisted, login-gated user saved filters that hydrate the filter slices on
 * sign-in. `recentTimeWindow`/`trendTimeWindow` are per-page defaults; `locations`
 * is a single shared default set applied to both pages. The two
 * `*ActiveKeywordListId` fields name the active keyword list per page (the
 * built-in id `"builtin-swe"`, a user list id, or `null` for no keyword filter).
 */
export interface SavedFilters {
  recentTimeWindow: TimeWindow;
  trendTimeWindow: TimeWindow;
  locations: string[];
  recentActiveKeywordListId: string | null;
  trendActiveKeywordListId: string | null;
}

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
  /** Enrichment category slugs (multi-select OR; empty/undefined = All). Jobs not yet enriched (category null) are always shown. */
  category?: string[];
  /** Enrichment level slugs (multi-select OR; 'entry' also matches new_grad). Jobs not yet enriched (level null) are always shown. */
  level?: string[];
}

/**
 * Structurally identical to `GraphFilters`. Retained only as generic
 * scaffolding for the `createFilterSlice` factory (its `'list'` slice name and
 * `Filters`/`FiltersWithDepartments` unions) — no Redux slice consumes it. The
 * company page now uses a single `graphFilters` source that drives both the
 * graph and the list.
 */
export interface ListFilters {
  timeWindow: TimeWindow;
  searchTags?: SearchTag[];
  location?: string[];
  department?: string[];
  employmentType?: string;
  softwareOnly: boolean;
  /** Enrichment category slugs (multi-select OR; empty/undefined = All). Jobs not yet enriched (category null) are always shown. */
  category?: string[];
  /** Enrichment level slugs (multi-select OR; 'entry' also matches new_grad). Jobs not yet enriched (level null) are always shown. */
  level?: string[];
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
  /** Enrichment category slugs (multi-select OR; empty/undefined = All). Jobs not yet enriched (category null) are always shown. */
  category?: string[];
  /** Enrichment level slugs (multi-select OR; 'entry' also matches new_grad). Jobs not yet enriched (level null) are always shown. */
  level?: string[];
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


/**
 * One dropdown option from GET /api/jobs/facets (job_categories / job_levels).
 * `parentSlug` encodes the level hierarchy (new_grad -> entry) so the
 * client-side filter expansion stays data-driven.
 */
export interface FacetOption {
  slug: string;
  label: string;
  sortOrder: number;
  parentSlug?: string | null;
}

/** GET /api/jobs/facets response. */
export interface JobFacets {
  categories: FacetOption[];
  levels: FacetOption[];
}
