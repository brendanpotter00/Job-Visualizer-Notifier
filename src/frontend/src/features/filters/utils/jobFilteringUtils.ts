import type {
  Job,
  JobLocation,
  TimeWindow,
  SearchTag,
  GraphFilters,
  ListFilters,
  RecentJobsFilters,
} from '../../../types';
import { getTimeWindowDuration } from '../../../lib/date.ts';
import { LEVEL_FILTER_EXPANSION } from '../../../constants/enrichment.ts';
import { US_STATE_NAME_TO_CODE, stripUsSuffix } from '../../../lib/location.ts';

/**
 * Shared utility functions for job filtering logic.
 * These pure functions can be used by both graph and list selectors.
 */

/**
 * Check if a job is within a specific time window.
 *
 * Keyed on `firstSeenAt` (when WE first saw the listing), NOT the ATS posted
 * date — companies reuse/repost old listings, so posted-date windowing buries
 * freshly re-listed jobs. See `Job.firstSeenAt` and backend
 * `docs/database-schema.md` ("Recency fields — which to trust").
 */
export function isJobWithinTimeWindow(jobFirstSeenAt: string, timeWindow: TimeWindow): boolean {
  if (timeWindow === 'all') {
    return true;
  }

  const now = new Date();
  const jobDate = new Date(jobFirstSeenAt);
  const durationMs = getTimeWindowDuration(timeWindow);
  const cutoffTime = now.getTime() - durationMs;

  return jobDate.getTime() >= cutoffTime;
}

/**
 * Check if a job matches search tags (include/exclude logic)
 */
export function matchesSearchTags(job: Job, searchTags: SearchTag[] | undefined): boolean {
  if (!searchTags || searchTags.length === 0) {
    return true;
  }

  const searchableText = [job.title, job.department, job.team, job.location, ...(job.tags || [])]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  const includeTags = searchTags.filter((t) => t.mode === 'include');
  const excludeTags = searchTags.filter((t) => t.mode === 'exclude');

  // Include logic: If include tags exist, job must match at least one (OR logic)
  if (includeTags.length > 0) {
    const matchesAnyIncludeTag = includeTags.some((tag) =>
      searchableText.includes(tag.text.toLowerCase())
    );

    if (!matchesAnyIncludeTag) {
      return false;
    }
  }

  // Exclude logic: Job must NOT match any exclude tags (AND NOT logic)
  if (excludeTags.length > 0) {
    const matchesAnyExcludeTag = excludeTags.some((tag) =>
      searchableText.includes(tag.text.toLowerCase())
    );

    if (matchesAnyExcludeTag) {
      return false;
    }
  }

  return true;
}

/** Hierarchy tier of a (possibly synthesized) location option. */
type LocationTier = 'country' | 'region' | 'city' | 'remote';

/** Structured descriptor a selected location option resolves to. */
export interface LocationDescriptor {
  tier: LocationTier;
  city: string | null;
  region: string | null;
  country: string | null;
  remoteScope: string | null;
}

/** Lookup of every location tag present on the jobs being filtered. */
export interface LocationIndex {
  /** canonicalName -> descriptor, for every real tag on the jobs. */
  descriptors: Map<string, LocationDescriptor>;
}

/**
 * Structured fields of one canonical location, cached when the user picks it
 * from the server-side location search. Mirrors the columns of the `locations`
 * table (minus the display name / id). Seeded into the `LocationIndex` so a
 * selected location resolves hierarchically even when NO currently-loaded job
 * carries that exact tag — e.g. selecting "Japan" filters city-only Tokyo jobs,
 * which the label-only fallbacks (US-state names) could never resolve.
 */
export interface LocationCatalogEntry {
  kind: string;
  city: string | null;
  region: string | null;
  country: string | null;
  remoteScope: string | null;
}

/** canonicalName -> structured fields, for every location the user has picked. */
export type LocationCatalog = Record<string, LocationCatalogEntry>;

/** Trim + upper-case a code; empty becomes null so comparisons stay strict. */
const normCode = (value: string | null | undefined): string | null =>
  value == null ? null : value.trim().toUpperCase() || null;

/** Hard-coded descriptor for the "United States" meta-option. */
const UNITED_STATES_DESCRIPTOR: LocationDescriptor = {
  tier: 'country',
  city: null,
  region: null,
  country: 'US',
  remoteScope: null,
};

/** Normalize the structured fields of a location into a descriptor. Shared by
 * job tags and catalog entries so both derive tier + codes identically. */
function fieldsToDescriptor(
  kind: string,
  city: string | null | undefined,
  region: string | null | undefined,
  country: string | null | undefined,
  remoteScope: string | null | undefined
): LocationDescriptor {
  const tier: LocationTier =
    kind === 'country' || kind === 'region' || kind === 'remote' ? kind : 'city';
  return {
    tier,
    city: city ? city.trim() : null,
    region: normCode(region),
    country: normCode(country),
    remoteScope: normCode(remoteScope),
  };
}

/** Map a raw JobLocation tag to a normalized descriptor. */
function tagToDescriptor(tag: JobLocation): LocationDescriptor {
  return fieldsToDescriptor(tag.kind, tag.city, tag.region, tag.country, tag.remoteScope);
}

/**
 * Build a lookup of every location tag present on `jobs`, keyed by canonicalName,
 * so the matcher can resolve a selected filter string back to its structured
 * tier and do hierarchical (region→city, country→everything) containment.
 */
export function buildLocationIndex(jobs: Job[]): LocationIndex {
  const descriptors = new Map<string, LocationDescriptor>();
  for (const job of jobs) {
    if (!job.locations) continue;
    for (const tag of job.locations) {
      if (!descriptors.has(tag.canonicalName)) {
        descriptors.set(tag.canonicalName, tagToDescriptor(tag));
      }
    }
  }
  return { descriptors };
}

/**
 * Seed `index` with descriptors for locations the user picked from search that
 * aren't already present as a loaded-job tag. Loaded-job tags win (they're the
 * ground truth for jobs actually on the page); catalog entries only fill gaps —
 * a selection whose jobs are outside the current time window, or a parent
 * (country/region) selection no loaded job carries as an exact tag. This is
 * what lets a selection filter correctly BEFORE its jobs are loaded and lets
 * non-US / irregular locations resolve at all.
 */
export function mergeCatalogIntoIndex(index: LocationIndex, catalog: LocationCatalog): void {
  for (const [canonicalName, entry] of Object.entries(catalog)) {
    if (!index.descriptors.has(canonicalName)) {
      index.descriptors.set(
        canonicalName,
        fieldsToDescriptor(entry.kind, entry.city, entry.region, entry.country, entry.remoteScope)
      );
    }
  }
}

/**
 * Resolve a selected filter string to a structured descriptor:
 *  1. "United States" meta-option -> US country descriptor.
 *  2. A canonicalName in the index -> its descriptor. The index holds every
 *     loaded-job tag PLUS any location the user picked from search (seeded via
 *     `mergeCatalogIntoIndex`), so this path now resolves non-US countries and
 *     irregular regions the string-only fallback below can't.
 *  3. A "<State>, US" option (no index entry) -> derived US region descriptor
 *     via the state-name lookup.
 * Returns null when unresolvable, so that token matches nothing.
 */
export function resolveSelectedDescriptor(
  filterLoc: string,
  index: LocationIndex
): LocationDescriptor | null {
  if (filterLoc === 'United States') {
    return UNITED_STATES_DESCRIPTOR;
  }

  const known = index.descriptors.get(filterLoc);
  if (known) {
    return known;
  }

  const stateCode = US_STATE_NAME_TO_CODE[stripUsSuffix(filterLoc)];
  if (stateCode) {
    return { tier: 'region', city: null, region: stateCode, country: 'US', remoteScope: null };
  }
  return null;
}

/**
 * Check if a job matches the location filter (multi-select with OR logic) using
 * HIERARCHICAL containment rather than exact canonicalName equality:
 *
 *  - country filter -> any non-remote tag with the same country
 *  - region filter  -> any non-remote tag with the same region AND country
 *                      (the country guard prevents cross-country region clashes,
 *                       e.g. Ontario "ON"/CA vs a US region)
 *  - city filter    -> any tag with the same city + region + country
 *  - remote filter  -> any remote tag with the same remoteScope
 *
 * Remote tags are matched only by an explicit remote selection — geographic
 * filters return on-site/hybrid roles, and "Remote (US)" stays its own option.
 *
 * Matches against the job's normalized canonical tags (`job.locations`); a job
 * with no tags (unnormalized or failed) matches no specific filter — there is
 * intentionally no raw-string fallback. The `index` is built once per filter
 * pass from the jobs being filtered (see `buildLocationIndex`).
 */
export function matchesLocation(
  job: Job,
  locations: string[] | undefined,
  index: LocationIndex
): boolean {
  if (!locations || locations.length === 0) {
    return true;
  }

  const tags = job.locations;
  if (!tags || tags.length === 0) {
    return false;
  }

  return locations.some((filterLoc) => {
    // Baseline: an exact canonical match always counts. Preserves matching for
    // tags that carry only a canonicalName (no structured city/region fields).
    if (tags.some((tag) => tag.canonicalName === filterLoc)) {
      return true;
    }

    // Hierarchical containment via structured fields for parent selections.
    const want = resolveSelectedDescriptor(filterLoc, index);
    if (!want) {
      return false;
    }

    return tags.some((rawTag) => {
      const tag = tagToDescriptor(rawTag);
      switch (want.tier) {
        case 'country':
          return tag.tier !== 'remote' && tag.country != null && tag.country === want.country;
        case 'region':
          return (
            tag.tier !== 'remote' &&
            tag.region != null &&
            tag.region === want.region &&
            tag.country === want.country
          );
        case 'city':
          return (
            tag.city != null &&
            want.city != null &&
            tag.city.toUpperCase() === want.city.toUpperCase() &&
            tag.region === want.region &&
            tag.country === want.country
          );
        case 'remote':
          if (tag.tier !== 'remote') return false;
          return want.remoteScope == null || tag.remoteScope === want.remoteScope;
        default:
          return false;
      }
    });
  });
}

/**
 * Check if a job matches department filter (multi-select with OR logic)
 */
export function matchesDepartment(job: Job, departments: string[] | undefined): boolean {
  if (!departments || departments.length === 0) {
    return true;
  }

  return departments.some((filterDept) => job.department === filterDept);
}

/**
 * Check if a job matches employment type filter
 */
export function matchesEmploymentType(job: Job, employmentType: string | undefined): boolean {
  if (!employmentType) {
    return true;
  }

  return job.employmentType === employmentType;
}

/**
 * Check if a job matches the enrichment category filter (multi-select, OR
 * logic). An empty/undefined selection means "All". Unenriched jobs
 * (category null) are ALWAYS shown even while a filter is active: the AI
 * enrichment pipeline takes days to work through the backlog, so hiding
 * not-yet-tagged jobs would make users miss perfectly good postings. The
 * filter therefore only narrows among jobs that HAVE a category.
 */
export function matchesCategory(job: Job, categories: string[] | undefined): boolean {
  if (!categories || categories.length === 0) {
    return true;
  }
  if (job.category == null) {
    return true;
  }
  return categories.includes(job.category);
}

/**
 * Check if a job matches the enrichment level filter (multi-select, OR logic),
 * honoring the new_grad ⊂ entry hierarchy: selecting 'entry' also surfaces
 * new-grad jobs (the server's _LEVEL_FILTER_EXPANSION mirrored client-side —
 * the HANDOFF's load-bearing contract; without it new-grad jobs vanish from
 * the entry view). Like the category filter, unenriched jobs (level null) are
 * ALWAYS shown; the filter only narrows among jobs that HAVE a level.
 */
export function matchesLevel(job: Job, levels: string[] | undefined): boolean {
  if (!levels || levels.length === 0) {
    return true;
  }
  if (job.level == null) {
    return true;
  }
  const jobLevel = job.level;
  return levels.some((level) => (LEVEL_FILTER_EXPANSION[level] ?? [level]).includes(jobLevel));
}

/**
 * Check if a job matches company filter (multi-select with OR logic)
 */
export function matchesCompany(job: Job, companies: string[] | undefined): boolean {
  if (!companies || companies.length === 0) {
    return true;
  }

  return companies.some((filterCompany) => job.company === filterCompany);
}

/**
 * Filter jobs based on provided filters
 * Works with GraphFilters, ListFilters, and RecentJobsFilters
 *
 * `locationCatalog` (optional) carries structured fields for locations the user
 * picked from the server-side search but that may not exist as a tag on any
 * currently-loaded job; seeding them into the index lets those selections
 * filter correctly (see `mergeCatalogIntoIndex`).
 */
export function filterJobsByFilters(
  jobs: Job[],
  filters: GraphFilters | ListFilters | RecentJobsFilters,
  locationCatalog?: LocationCatalog
): Job[] {
  // Build the hierarchical location index ONCE from the full candidate set so a
  // region/country selection resolves against every available tag.
  const locationIndex = buildLocationIndex(jobs);
  if (locationCatalog) {
    mergeCatalogIntoIndex(locationIndex, locationCatalog);
  }

  return jobs.filter((job: Job) => {
    // Time window filter (recency = when we first saw the job, not ATS posted date)
    if (!isJobWithinTimeWindow(job.firstSeenAt, filters.timeWindow)) {
      return false;
    }

    // Search tags filter (include/exclude logic)
    if (!matchesSearchTags(job, filters.searchTags)) {
      return false;
    }

    // Location filter (multi-select with OR logic, hierarchical containment)
    if (!matchesLocation(job, filters.location, locationIndex)) {
      return false;
    }

    // Department filter (multi-select with OR logic)
    // Only check if department exists on filters (GraphFilters/ListFilters only)
    if ('department' in filters && !matchesDepartment(job, filters.department)) {
      return false;
    }

    // Employment type filter
    if (!matchesEmploymentType(job, filters.employmentType)) {
      return false;
    }

    // Enrichment facet filters (multi-select OR; every filter shape owns both).
    // Unenriched jobs pass both — they're never hidden by an active facet.
    if (!matchesCategory(job, filters.category)) {
      return false;
    }
    if (!matchesLevel(job, filters.level)) {
      return false;
    }

    // Company filter (multi-select with OR logic)
    // Only check if company exists on filters (RecentJobsFilters only)
    if ('company' in filters && !matchesCompany(job, filters.company)) {
      return false;
    }

    return true;
  });
}
