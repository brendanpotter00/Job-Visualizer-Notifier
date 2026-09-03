import type { Job, RecentJobsFilters, SearchTag, TimeWindow } from '../../types';
import { COMPANIES } from '../../config/companies';
import {
  setSearchTags,
  setSoftwareOnlyInFilters,
} from '../../features/filters/utils/filterReducerUtils';
import type { ToolCtx, ToolResult } from '../types';

// ---------------------------------------------------------------------------
// Result envelope helpers
// ---------------------------------------------------------------------------

/** Success result — `content` is the JSON text form of `structuredContent`. */
export function ok(structuredContent: unknown): ToolResult {
  return {
    content: [{ type: 'text', text: JSON.stringify(structuredContent) }],
    structuredContent,
    isError: false,
  };
}

/**
 * Tool-level error result. Surfaces a readable `error` message (plus any extra
 * fields) as `structuredContent` and sets `isError`. NOT a thrown exception —
 * the shim returns this so Playwright can assert on the error shape.
 */
export function err(message: string, extra?: Record<string, unknown>): ToolResult {
  const structuredContent = { error: message, ...(extra ?? {}) };
  return {
    content: [{ type: 'text', text: JSON.stringify(structuredContent) }],
    structuredContent,
    isError: true,
  };
}

// ---------------------------------------------------------------------------
// RTK Query dispatch helpers
// ---------------------------------------------------------------------------

/** Structural view of a query `initiate()` dispatch result. */
interface QueryDispatchResult<T> {
  unwrap(): Promise<T>;
  unsubscribe(): void;
}

/** Structural view of a mutation `initiate()` dispatch result. */
interface MutationDispatchResult<T> {
  unwrap(): Promise<T>;
  reset(): void;
}

/**
 * Run a one-shot RTK Query read and drop its subscription afterward, so a tool
 * call does not leave a cache entry pinned for the session.
 */
export async function runQuery<T>(result: QueryDispatchResult<T>): Promise<T> {
  try {
    return await result.unwrap();
  } finally {
    result.unsubscribe();
  }
}

/** Run an RTK Query mutation and drop its one-shot cache entry afterward. */
export async function runMutation<T>(result: MutationDispatchResult<T>): Promise<T> {
  try {
    return await result.unwrap();
  } finally {
    result.reset();
  }
}

// ---------------------------------------------------------------------------
// Argument coercion (the shim does not JSON-Schema-validate; parse defensively)
// ---------------------------------------------------------------------------

export const TIME_WINDOW_ENUM = [
  '30m',
  '1h',
  '3h',
  '6h',
  '12h',
  '24h',
  '3d',
  '7d',
  '14d',
  '30d',
  '90d',
  '180d',
  'all',
] as const;

export function asString(v: unknown): string | undefined {
  return typeof v === 'string' ? v : undefined;
}

export function asBool(v: unknown): boolean | undefined {
  return typeof v === 'boolean' ? v : undefined;
}

export function asInt(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? Math.trunc(v) : undefined;
}

/** Non-empty array of strings, or undefined (an empty result reads as absent). */
export function asStringArray(v: unknown): string[] | undefined {
  if (!Array.isArray(v)) return undefined;
  const out = v.filter((x): x is string => typeof x === 'string');
  return out.length > 0 ? out : undefined;
}

export function asTimeWindow(v: unknown, fallback: TimeWindow): TimeWindow {
  return typeof v === 'string' && (TIME_WINDOW_ENUM as readonly string[]).includes(v)
    ? (v as TimeWindow)
    : fallback;
}

/** Parsed shape shared by `search_jobs` and `apply_feed_filters`. */
export interface RecentToolArgs {
  include?: string[];
  exclude?: string[];
  category?: string[];
  level?: string[];
  company?: string[];
  location?: string[];
  timeWindow: TimeWindow;
  employmentType?: string;
  softwareOnly?: boolean;
}

export function parseRecentArgs(args: Record<string, unknown>): RecentToolArgs {
  return {
    include: asStringArray(args.include),
    exclude: asStringArray(args.exclude),
    category: asStringArray(args.category),
    level: asStringArray(args.level),
    company: asStringArray(args.company),
    location: asStringArray(args.location),
    timeWindow: asTimeWindow(args.timeWindow, 'all'),
    employmentType: asString(args.employmentType),
    softwareOnly: asBool(args.softwareOnly),
  };
}

// ---------------------------------------------------------------------------
// Company resolution
// ---------------------------------------------------------------------------

/**
 * Resolve a user-supplied company token (id OR display name, case-insensitive)
 * to a canonical company id. Returns null when nothing matches — so callers can
 * drop an unresolvable token rather than accidentally filtering to empty.
 */
export function resolveCompany(nameOrId: string): string | null {
  const needle = nameOrId.trim().toLowerCase();
  if (needle.length === 0) return null;
  const byId = COMPANIES.find((c) => c.id.toLowerCase() === needle);
  if (byId) return byId.id;
  const byName = COMPANIES.find((c) => c.name.toLowerCase() === needle);
  return byName ? byName.id : null;
}

/** Every company served by the batched backend-scraper `/api/jobs` endpoint. */
export function backendScraperCompanyIds(): string[] {
  return COMPANIES.filter((c) => c.ats === 'backend-scraper').map((c) => c.id);
}

// ---------------------------------------------------------------------------
// Filter construction (reuse the slice's own mutation utils)
// ---------------------------------------------------------------------------

/**
 * Build a `RecentJobsFilters` from parsed tool args, reusing the filter slice's
 * own mutation utils so keyword-tag and softwareOnly semantics match the UI
 * byte-for-byte. Company tokens are resolved to ids; unresolved ones are
 * dropped. This is the predicate `search_jobs` applies client-side, mirroring
 * `selectRecentFilteredJobs`.
 */
export function buildRecentFilters(args: RecentToolArgs): RecentJobsFilters {
  const filters: RecentJobsFilters = {
    timeWindow: args.timeWindow,
    searchTags: undefined,
    location: undefined,
    employmentType: undefined,
    softwareOnly: false,
    company: undefined,
    category: undefined,
    level: undefined,
  };

  const tags = buildSearchTags(args.include, args.exclude);
  if (tags.length > 0) setSearchTags(filters, tags);

  if (args.location) filters.location = args.location;
  if (args.category) filters.category = args.category;
  if (args.level) filters.level = args.level;
  if (args.employmentType) filters.employmentType = args.employmentType;

  if (args.company) {
    const ids = args.company
      .map(resolveCompany)
      .filter((id): id is string => id !== null);
    filters.company = ids.length > 0 ? ids : undefined;
  }

  // softwareOnly last: it mutates searchTags via the shared util, so it must run
  // after any explicit include/exclude tags are already in place.
  if (args.softwareOnly) setSoftwareOnlyInFilters(filters, true);

  return filters;
}

/** Turn include/exclude keyword lists into the slice's `SearchTag[]` shape. */
export function buildSearchTags(
  include: string[] | undefined,
  exclude: string[] | undefined
): SearchTag[] {
  return [
    ...(include ?? []).map((text): SearchTag => ({ text, mode: 'include' })),
    ...(exclude ?? []).map((text): SearchTag => ({ text, mode: 'exclude' })),
  ];
}

// ---------------------------------------------------------------------------
// Navigation (Tier-2 tools drive the real router; fall back to History API)
// ---------------------------------------------------------------------------

/**
 * Navigate via the captured router `navigate`. When the bridge is absent
 * (store-only harness), fall back to the History API + a `popstate` event so a
 * `BrowserRouter` still updates. Documented, deliberate degradation (§2.5).
 */
export function navigateTo(ctx: ToolCtx, to: string): void {
  const navigate = ctx.getNavigate();
  if (navigate) {
    navigate(to);
    return;
  }
  window.history.pushState('', '', to);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

// ---------------------------------------------------------------------------
// Job serialization (the ONE place a Job is shaped for the wire; never `raw`)
// ---------------------------------------------------------------------------

export interface JobSummary {
  id: string;
  source: string;
  company: string;
  title: string;
  team?: string;
  location?: string;
  isRemote?: boolean;
  employmentType?: string;
  firstSeenAt: string;
  url: string;
  category?: string | null;
  level?: string | null;
}

/** Full posting detail; same stable field set as the summary (never `raw`). */
export type JobDetail = JobSummary;

export function toJobSummary(job: Job): JobSummary {
  return {
    id: job.id,
    source: job.source,
    company: job.company,
    title: job.title,
    team: job.team,
    location: job.location,
    isRemote: job.isRemote,
    employmentType: job.employmentType,
    firstSeenAt: job.firstSeenAt,
    url: job.url,
    category: job.category ?? null,
    level: job.level ?? null,
  };
}

export function toJobDetail(job: Job): JobDetail {
  return toJobSummary(job);
}
