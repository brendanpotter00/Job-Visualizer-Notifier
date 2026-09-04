import type { BackendJobListing } from '../../api/types';
import { jobsApi, STALE_CURSOR_STATUS } from '../../features/jobs/jobsApi';
import {
  buildSearchJobsArgs,
  buildSearchJobsQuery,
  sinceForTimeWindow,
} from '../../features/jobs/searchJobsArgs';
import { validateSearchJobsResponse } from '../../features/jobs/validateSearchJobsResponse';
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
 * `search_jobs` pages `GET /api/jobs/search`, which applies the whole filter set
 * server-side and pages the RESULT. The endpoint's own `nextCursor` is opaque and
 * filter-bound; the tool wraps it in ITS OWN opaque cursor that additionally
 * carries the FROZEN recency bound (`since`).
 *
 * A stateless tool has no debounced snapshot to freeze `since` on the way the UI
 * does, so if every call recomputed `sinceForTimeWindow(timeWindow, Date.now())`,
 * page 2 (issued seconds after page 1) would send a different `since`, move the
 * server's cursor fingerprint, and 409. Baking `since` into the tool cursor keeps
 * it frozen for the walk with no tool-side state. `limit` is deliberately NOT in
 * the cursor, so page size stays freely changeable mid-walk.
 *
 * A malformed/absent tool cursor decodes to `null` — a fresh page-1 walk — the
 * same "restart rather than error" contract the old composite cursor made.
 */
interface ToolCursor {
  /** The server's opaque `nextCursor`, replayed verbatim. */
  c: string;
  /** The recency bound frozen at page 1, replayed so the fingerprint holds. */
  s: string;
}

function decodeToolCursor(cursor: string | undefined): ToolCursor | null {
  if (!cursor) return null;
  try {
    const parsed: unknown = JSON.parse(atob(cursor));
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const record = parsed as Record<string, unknown>;
      if (typeof record.c === 'string' && typeof record.s === 'string') {
        return { c: record.c, s: record.s };
      }
    }
  } catch {
    // Malformed / stale tool cursor -> fresh walk (page 1).
  }
  return null;
}

function encodeToolCursor(payload: ToolCursor): string {
  return btoa(JSON.stringify(payload));
}

export function tier1Read(ctx: ToolCtx): WebMcpToolDef[] {
  const search_jobs: WebMcpToolDef = {
    name: 'search_jobs',
    description:
      'Search open job postings across tracked companies via server-side filtering (GET /api/jobs/search); every filter (category, level, company, location, keyword include/exclude, time window) is applied by the server. Returns serialized job summaries plus meta { filteredTotal, last24h, last3h, returned, nextCursor, hasMore }. Page with the opaque nextCursor: the time window is FROZEN at the first call and echoed inside the cursor, so timeWindow on a follow-up (cursor) call is ignored; change any filter to start a fresh walk.',
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
          description:
            'Opaque nextCursor from a prior call. Filter-bound and carries the frozen time window; echo it verbatim to get the next page. A malformed cursor restarts from page 1; if the server reports it stale (a filter changed underneath it) the call errors with status 409 — drop the cursor and search again.',
        },
      },
    },
    annotations: { readOnlyHint: true },
    execute: async (rawArgs) => {
      const parsed = parseRecentArgs(rawArgs);
      const limit = Math.min(Math.max(asInt(rawArgs.limit) ?? 100, 1), 500);
      const priorCursor = decodeToolCursor(asString(rawArgs.cursor));

      // Freeze `since` for the walk: page 1 computes it from `timeWindow`; a
      // follow-up reuses the value baked into the tool cursor (the endpoint folds
      // `since` into its cursor fingerprint, so recomputing it here would 409).
      const since = priorCursor ? priorCursor.s : sinceForTimeWindow(parsed.timeWindow, Date.now());
      const serverCursor = priorCursor ? priorCursor.c : null;

      // Reuse the exact builders the Recent page's read path uses — no duplicated
      // filter or query logic. `enabledCompanyIds: null` scopes only by the
      // agent's explicit `company` filter (never an operator preference), and
      // `isSignedOut: false` skips the signed-out overlay's row cap.
      const filters = buildRecentFilters(parsed);
      const args = buildSearchJobsArgs({
        filters,
        enabledCompanyIds: null,
        since,
        isSignedOut: false,
      });
      // Unreachable with `enabledCompanyIds: null` (the disjoint path needs a
      // non-null enabled list), but guarded: `null` means "provably no matches".
      if (args === null) {
        return ok({
          jobs: [],
          meta: {
            filteredTotal: 0,
            last24h: 0,
            last3h: 0,
            returned: 0,
            serverReturned: 0,
            nextCursor: null,
            hasMore: false,
          },
        });
      }
      // The builder hardcodes the page-size to the Recent feed's batch; the tool
      // owns its own clamped `limit`, and changing it mid-walk is legal (limit is
      // excluded from the cursor fingerprint).
      const finalArgs = { ...args, limit };

      let res: Response;
      try {
        res = await fetch(`/api/jobs/search?${buildSearchJobsQuery(finalArgs, serverCursor)}`, {
          headers: { Accept: 'application/json' },
        });
      } catch (e) {
        return err(`search_jobs fetch failed: ${e instanceof Error ? e.message : 'network error'}`);
      }
      if (!res.ok) {
        if (res.status === STALE_CURSOR_STATUS) {
          return err('search_jobs cursor is stale — drop it and call again with no cursor.', {
            status: STALE_CURSOR_STATUS,
          });
        }
        return err(`search_jobs failed (${res.status})`, { status: res.status });
      }

      let body;
      try {
        body = validateSearchJobsResponse(await res.json(), { isFirstPage: serverCursor === null });
      } catch (e) {
        return err(
          `search_jobs response invalid: ${e instanceof Error ? e.message : 'bad response shape'}`
        );
      }

      // Server already filtered and ordered the rows — no client-side filter or
      // sort. Same transformer the Recent page uses, so the mapping stays single.
      const jobs = body.jobs.map((row) => transformBackendJob(row, row.company)).map(toJobSummary);
      const nextCursor = body.nextCursor ? encodeToolCursor({ c: body.nextCursor, s: since }) : null;

      return ok({
        jobs,
        meta: {
          // Counts ride page 1 only (cursor pages omit them); null there.
          filteredTotal: body.counts?.total ?? null,
          last24h: body.counts?.last24h ?? null,
          last3h: body.counts?.last3h ?? null,
          returned: jobs.length,
          // Back-compat alias; on the server-side path it equals `returned`
          // (rows on THIS page), not a pre-filter count.
          serverReturned: jobs.length,
          nextCursor,
          hasMore: body.nextCursor !== null,
        },
      });
    },
  };

  const list_filter_options: WebMcpToolDef = {
    name: 'list_filter_options',
    description:
      'List the enrichment filter catalog (categories and levels) from GET /api/jobs/facets; returns { categories, levels } with slug/label/sortOrder each.',
    inputSchema: { type: 'object', additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: true },
    execute: async () => {
      try {
        const facets = await runQuery(ctx.store.dispatch(jobsApi.endpoints.getFacets.initiate()));
        return ok({ categories: facets.categories, levels: facets.levels });
      } catch (e) {
        return err(
          `list_filter_options failed: ${e instanceof Error ? e.message : 'unknown error'}`
        );
      }
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
      try {
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
      } catch (e) {
        return err(`list_companies failed: ${e instanceof Error ? e.message : 'unknown error'}`);
      }
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
      try {
        const locations = await runQuery(
          ctx.store.dispatch(locationsApi.endpoints.searchLocations.initiate({ q, limit, openOnly }))
        );
        return ok({ locations });
      } catch (e) {
        return err(`search_locations failed: ${e instanceof Error ? e.message : 'unknown error'}`);
      }
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

      try {
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
      } catch (e) {
        return err(
          `get_company_hiring_trend failed: ${e instanceof Error ? e.message : 'unknown error'}`
        );
      }
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
