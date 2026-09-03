import type { Job } from '../../types';
import type { BackendJobListing } from '../../api/types';
import { chunkCompanyIds, fetchJobsPage } from '../../api/clients/backendScraperClient';
import { jobsWindowForTimeWindow, sinceForWindow } from '../../features/jobs/jobsApi';
import { jobsApi } from '../../features/jobs/jobsApi';
import { chunkKey } from '../../features/jobs/keysetWalk';
import { filterJobsByFilters } from '../../features/filters/utils/jobFilteringUtils';
import { selectLocationCatalog } from '../../features/locations/locationCatalogSlice';
import { companiesApi } from '../../features/companies/companiesApi';
import { locationsApi } from '../../features/locations/locationsApi';
import { transformBackendJob } from '../../api/transformers/backendScraperTransformer';
import { bucketJobsByTime } from '../../lib/timeBucketing';
import type { ToolCtx, WebMcpToolDef } from '../types';
import {
  asBool,
  asInt,
  asString,
  asTimeWindow,
  backendScraperCompanyIds,
  buildRecentFilters,
  err,
  ok,
  parseRecentArgs,
  resolveCompany,
  runQuery,
  toJobDetail,
  toJobSummary,
  TIME_WINDOW_ENUM,
} from './shared';

/**
 * `search_jobs` presents ONE opaque cursor over what is really a per-chunk
 * keyset walk (the backend mints one `X-Next-Cursor` per `/api/jobs?companies=`
 * request, and >50 companies are split across several chunks). The composite
 * cursor is a base64 JSON map of `chunkKey -> cursor`, opaque to the caller and
 * filter-bound: a stale/malformed value decodes to an empty map, restarting the
 * walk from page 1 rather than 409-ing (see catalog "known limits").
 */
function decodeCursor(cursor: string | undefined): Record<string, string> {
  if (!cursor) return {};
  try {
    const parsed: unknown = JSON.parse(atob(cursor));
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof v === 'string') out[k] = v;
      }
      return out;
    }
  } catch {
    // Malformed / stale cursor -> fresh walk (cursors are filter-bound).
  }
  return {};
}

function encodeCursor(map: Record<string, string>): string {
  return btoa(JSON.stringify(map));
}

export function tier1Read(ctx: ToolCtx): WebMcpToolDef[] {
  const search_jobs: WebMcpToolDef = {
    name: 'search_jobs',
    description:
      'Search open job postings across tracked companies (server keyset fetch + the app’s own client-side filters); returns serialized job summaries plus filteredTotal/serverReturned/nextCursor meta.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        include: {
          type: 'array',
          items: { type: 'string' },
          description: 'Keyword must-match (OR within, applied to title/team/location text).',
        },
        exclude: {
          type: 'array',
          items: { type: 'string' },
          description: 'Keyword must-not-match.',
        },
        category: {
          type: 'array',
          items: { type: 'string' },
          description: 'Enrichment category slugs from list_filter_options (OR).',
        },
        level: {
          type: 'array',
          items: { type: 'string' },
          description: "Enrichment level slugs; 'entry' also matches new_grad.",
        },
        company: {
          type: 'array',
          items: { type: 'string' },
          description: 'Company id or display name; omit for all companies.',
        },
        location: {
          type: 'array',
          items: { type: 'string' },
          description: 'Canonical location names from search_locations.',
        },
        timeWindow: {
          type: 'string',
          enum: [...TIME_WINDOW_ENUM],
          default: 'all',
        },
        limit: { type: 'integer', minimum: 1, maximum: 500, default: 100 },
        cursor: {
          type: 'string',
          description: 'Opaque nextCursor from a prior call; filter-bound (a filter change restarts the walk).',
        },
      },
    },
    annotations: { readOnlyHint: true },
    execute: async (rawArgs) => {
      const parsed = parseRecentArgs(rawArgs);
      const limit = Math.min(Math.max(asInt(rawArgs.limit) ?? 100, 1), 500);
      const cursorMapIn = decodeCursor(asString(rawArgs.cursor));

      // Server scope: resolved companies if given, else every backend-scraper
      // company (mirrors the Recent feed's fan-out).
      const scopedIds =
        parsed.company && parsed.company.length > 0
          ? parsed.company.map(resolveCompany).filter((id): id is string => id !== null)
          : backendScraperCompanyIds();

      const chunks = chunkCompanyIds(scopedIds);
      // Coarse server window (backend keyset supports 90d/180d/all); the precise
      // timeWindow is enforced again client-side by filterJobsByFilters.
      const since = sinceForWindow(jobsWindowForTimeWindow(parsed.timeWindow));

      let pages: Array<{ key: string; jobs: Job[]; nextCursor: string | null }>;
      try {
        pages = await Promise.all(
          chunks.map(async (chunk) => {
            const key = chunkKey(chunk);
            const page = await fetchJobsPage(chunk, { since, cursor: cursorMapIn[key], limit });
            return { key, jobs: page.jobs, nextCursor: page.nextCursor };
          })
        );
      } catch (e) {
        return err(`search_jobs fetch failed: ${e instanceof Error ? e.message : 'unknown error'}`);
      }

      const serverJobs: Job[] = [];
      const cursorMapOut: Record<string, string> = {};
      for (const { key, jobs, nextCursor } of pages) {
        serverJobs.push(...jobs);
        if (nextCursor) cursorMapOut[key] = nextCursor;
      }
      const serverReturned = serverJobs.length;

      const filters = buildRecentFilters(parsed);
      const locationCatalog = selectLocationCatalog(ctx.store.getState());
      const filtered = filterJobsByFilters(serverJobs, filters, locationCatalog).sort(
        (a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime()
      );
      const filteredTotal = filtered.length;
      const jobs = filtered.slice(0, limit).map(toJobSummary);

      const hasMore = Object.keys(cursorMapOut).length > 0;
      const nextCursor = hasMore ? encodeCursor(cursorMapOut) : null;

      return ok({ jobs, meta: { filteredTotal, serverReturned, nextCursor, hasMore } });
    },
  };

  const list_filter_options: WebMcpToolDef = {
    name: 'list_filter_options',
    description:
      'List the enrichment filter catalog (categories and levels) from GET /api/jobs/facets; returns { categories, levels } with slug/label/sortOrder each.',
    inputSchema: { type: 'object', additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: true },
    execute: async () => {
      const facets = await runQuery(ctx.store.dispatch(jobsApi.endpoints.getFacets.initiate()));
      return ok({ categories: facets.categories, levels: facets.levels });
    },
  };

  const list_companies: WebMcpToolDef = {
    name: 'list_companies',
    description:
      'List the curated company directory (GET /api/companies), optionally filtered by a case-insensitive substring over id/name; use it to resolve a company name to an id.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        query: {
          type: 'string',
          description: 'Optional case-insensitive substring over name/id.',
        },
      },
    },
    annotations: { readOnlyHint: true },
    execute: async (rawArgs) => {
      const query = asString(rawArgs.query)?.trim().toLowerCase();
      const companies = await runQuery(
        ctx.store.dispatch(companiesApi.endpoints.listCuratedCompanies.initiate())
      );
      const filtered = query
        ? companies.filter(
            (c) =>
              c.id.toLowerCase().includes(query) || c.displayName.toLowerCase().includes(query)
          )
        : companies;
      return ok({ companies: filtered });
    },
  };

  const search_locations: WebMcpToolDef = {
    name: 'search_locations',
    description:
      'Search canonical locations (GET /api/locations/search) for the location filter; returns matching { canonicalName, ... } descriptors.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      required: ['q'],
      properties: {
        q: { type: 'string', minLength: 1 },
        limit: { type: 'integer', minimum: 1, maximum: 50, default: 10 },
        openOnly: { type: 'boolean', default: false },
      },
    },
    annotations: { readOnlyHint: true },
    execute: async (rawArgs) => {
      const q = asString(rawArgs.q);
      if (!q || q.length < 1) return err('search_locations requires a non-empty `q`.');
      const limit = asInt(rawArgs.limit) ?? 10;
      const openOnly = asBool(rawArgs.openOnly) ?? false;
      const locations = await runQuery(
        ctx.store.dispatch(locationsApi.endpoints.searchLocations.initiate({ q, limit, openOnly }))
      );
      return ok({ locations });
    },
  };

  const get_job: WebMcpToolDef = {
    name: 'get_job',
    description:
      'Fetch one posting by (source, id) from GET /api/jobs/{source}/{id}; returns { job } with the apply url, title, company, location, firstSeenAt, category, level.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      required: ['source', 'id'],
      properties: {
        source: { type: 'string', description: 'ATS source id (job.source).' },
        id: { type: 'string', description: 'Posting id (job.id).' },
      },
    },
    annotations: { readOnlyHint: true },
    execute: async (rawArgs) => {
      const source = asString(rawArgs.source);
      const id = asString(rawArgs.id);
      if (!source || !id) return err('get_job requires string `source` and `id`.');
      let res: Response;
      try {
        res = await fetch(
          `/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(id)}`,
          { headers: { Accept: 'application/json' } }
        );
      } catch (e) {
        return err(`get_job fetch failed: ${e instanceof Error ? e.message : 'network error'}`);
      }
      if (!res.ok) {
        return err(`Job not found (${res.status}) for ${source}/${id}`, { status: res.status });
      }
      const raw = (await res.json()) as BackendJobListing;
      const job = transformBackendJob(raw, raw.company);
      return ok({ job: toJobDetail(job) });
    },
  };

  const get_company_hiring_trend: WebMcpToolDef = {
    name: 'get_company_hiring_trend',
    description:
      'Get a company’s hiring activity over time: fetches its postings (getJobsForCompany) and time-buckets them, returning { companyId, timeWindow, buckets, total }.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      required: ['company'],
      properties: {
        company: { type: 'string', description: 'Company id or display name.' },
        timeWindow: {
          type: 'string',
          enum: [...TIME_WINDOW_ENUM],
          default: '90d',
        },
      },
    },
    annotations: { readOnlyHint: true },
    execute: async (rawArgs) => {
      const companyToken = asString(rawArgs.company);
      if (!companyToken) return err('get_company_hiring_trend requires a `company`.');
      // Allow a raw id through even if it is not in COMPANIES (e.g. a user-added
      // board), falling back to the token when name resolution finds nothing.
      const companyId = resolveCompany(companyToken) ?? companyToken;
      const timeWindow = asTimeWindow(rawArgs.timeWindow, '90d');

      const result = await runQuery(
        ctx.store.dispatch(jobsApi.endpoints.getJobsForCompany.initiate({ companyId }))
      );
      const jobs = result.jobs;
      const buckets = bucketJobsByTime(jobs, timeWindow).map((b) => ({
        bucketStart: b.bucketStart,
        bucketEnd: b.bucketEnd,
        count: b.count,
      }));
      return ok({ companyId, timeWindow, buckets, total: jobs.length });
    },
  };

  return [
    search_jobs,
    list_filter_options,
    list_companies,
    search_locations,
    get_job,
    get_company_hiring_trend,
  ];
}
