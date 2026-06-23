import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

export type SignupProvider = 'google' | 'email' | 'other';

/**
 * Single source of truth for human-readable signup-provider labels.
 *
 * Typed as ``Record<SignupProvider, string>`` (not ``Record<string, string>``)
 * so adding a new provider on the backend forces a compile-time update
 * here rather than rendering a raw key like "github" to admins.
 *
 * Audit pass-3 found two copies in ``ProviderBars.tsx`` (used the
 * "Email / Auth0" label) and ``UserRosterTable.tsx`` (used the shorter
 * "Email" label) — both typed correctly but with DIFFERENT values, a
 * maintenance hazard. The more-verbose "Email / Auth0" is the canonical
 * choice because it disambiguates the underlying IdP for admins.
 */
export const PROVIDER_LABEL: Record<SignupProvider, string> = {
  google: 'Google',
  email: 'Email / Auth0',
  other: 'Other',
};

export interface AdminUserRow {
  id: string;
  email: string;
  displayName: string | null;
  signupProvider: SignupProvider;
  createdAt: string;
  /** Times this user has loaded/refreshed the app (POST /api/users/visit). */
  visitCount: number;
  /** ISO timestamp of the user's most recent load; null until their first visit. */
  lastVisitAt: string | null;
  isAdmin: boolean;
}

export interface AdminUsersStats {
  totalUsers: number;
  firstSignupAt: string | null;
  latestSignupAt: string | null;
  // Partial because the aggregate may omit zero-count providers. Typed
  // as ``SignupProvider`` so adding a new provider on the backend is a
  // compile-time error at every render site rather than rendering raw
  // keys to admins.
  byProvider: Partial<Record<SignupProvider, number>>;
}

/**
 * Envelope for the ``/api/admin/users`` response. Lifted to a named
 * export so the shape is described in exactly one place and the runtime
 * guard in ``transformResponse`` has a typed handle.
 */
export interface AdminUsersListResponse {
  users: AdminUserRow[];
}

/**
 * One row in the admin User Feedback table. Field names mirror the backend's
 * camelCased ``FeedbackResponse``. Null user fields ⇒ an anonymous submission.
 */
export interface FeedbackRow {
  id: string;
  message: string;
  userId: string | null;
  userEmail: string | null;
  displayName: string | null;
  createdAt: string;
}

export interface AdminFeedbackListResponse {
  feedback: FeedbackRow[];
  /** Total rows in the table (not just this page) — drives the server-side pager. */
  total: number;
}

/** One page request for the admin feedback list (server-side pagination). */
export interface AdminFeedbackPageArgs {
  page: number;
  rowsPerPage: number;
  sortDir: 'asc' | 'desc';
}

interface AdminApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}

// ───────────────────────────────────────────────────────────────────────────
// Location Normalization Monitor — types
//
// The backend serializes these as camelCase JSON. NOTE the two distinct id
// types: ``locations.id`` is a NUMBER (canonical-location PK) while a job
// listing id is a STRING. Typed accordingly so a future call site can't pass
// one where the other is expected.
// ───────────────────────────────────────────────────────────────────────────

/** Severity tag carried by an integrity invariant row. */
export type IntegritySeverity = 'ok' | 'warn' | 'crit';

/** Source of an alias mapping — model-inferred vs. human override. */
export type AliasSource = 'llm' | 'manual';

/**
 * Worker queue depth snapshot keyed by Procrastinate job state. Typed as a
 * loose record because the backend may add states; the UI reads a known
 * subset (``todo``/``doing``/``succeeded``/``failed``) defensively.
 */
export type NormalizeQueue = Record<string, number>;

export interface LocationHealth {
  schemaPresent: boolean;
  windowHours: number;
  nullBacklog: number;
  nullAged: number;
  done: number;
  failed: number;
  total: number;
  failedBlank: number;
  failedNonblank: number;
  /** Percentage in the range 0..100 (NOT a 0..1 fraction). */
  failedNonblankRatio: number;
  heartbeatAgeMinutes: number | null;
  normalizeQueue: NormalizeQueue;
  throughputInWindow: number | null;
  keyConfigured: boolean;
  dormant: boolean;
}

export interface IntegrityCheck {
  id: string;
  label: string;
  count: number;
  severity: IntegritySeverity;
}

interface IntegrityResponse {
  schemaPresent: boolean;
  checks: IntegrityCheck[];
}

/** A canonical location mapped from an alias. ``id`` is numeric. */
export interface CanonicalLocation {
  id: number;
  canonicalName: string;
  kind: string;
  city: string | null;
  region: string | null;
  country: string | null;
  remoteScope: string | null;
  position: number;
}

export interface AliasRow {
  rawText: string;
  source: AliasSource;
  confidence: number | null;
  locations: CanonicalLocation[];
}

export interface AliasListResponse {
  aliases: AliasRow[];
  total: number;
}

/** Canonical location in the reverse view (no ``position``). */
export interface ReverseLocation {
  id: number;
  canonicalName: string;
  kind: string;
  city: string | null;
  region: string | null;
  country: string | null;
  remoteScope: string | null;
}

export interface ReverseResult {
  location: ReverseLocation;
  rawTexts: string[];
}

export interface ReverseSearchResponse {
  results: ReverseResult[];
}

export interface AliasOriginal {
  original: string;
  jobIds: string[];
}

export interface AliasOriginalsResponse {
  rawText: string;
  total: number;
  originals: AliasOriginal[];
}

export interface ProblemJob {
  id: string;
  title: string | null;
  company: string | null;
  location: string | null;
  normalizationStatus: string | null;
  lastSeenAt: string | null;
}

export interface ProblemJobsResponse {
  jobs: ProblemJob[];
  total: number;
}

/** Editable canonical-location spec for the alias override mutation. */
export interface LocationSpec {
  canonicalName: string;
  kind: 'city' | 'region' | 'country' | 'remote';
  city?: string | null;
  region?: string | null;
  country?: string | null;
  remoteScope?: string | null;
}

// ─── Runtime-guard helpers (mirror the throwing style of listAdminUsers) ─────

function isRecord(v: unknown): v is Record<string, unknown> {
  return v != null && typeof v === 'object' && !Array.isArray(v);
}

function isIntegritySeverity(v: unknown): v is IntegritySeverity {
  return v === 'ok' || v === 'warn' || v === 'crit';
}

function isAliasSource(v: unknown): v is AliasSource {
  return v === 'llm' || v === 'manual';
}

function validateCanonicalLocation(loc: unknown, ctx: string, withPosition: boolean): void {
  if (!isRecord(loc)) {
    throw new Error(`Invalid ${ctx}: location entry is not an object`);
  }
  if (typeof loc.id !== 'number') {
    throw new Error(`Invalid ${ctx}: location.id must be a number`);
  }
  if (typeof loc.canonicalName !== 'string') {
    throw new Error(`Invalid ${ctx}: location.canonicalName must be a string`);
  }
  if (typeof loc.kind !== 'string') {
    throw new Error(`Invalid ${ctx}: location.kind must be a string`);
  }
  for (const field of ['city', 'region', 'country', 'remoteScope'] as const) {
    const val = loc[field];
    if (val !== null && val !== undefined && typeof val !== 'string') {
      throw new Error(`Invalid ${ctx}: location.${field} must be string or null`);
    }
  }
  if (withPosition && typeof loc.position !== 'number') {
    throw new Error(`Invalid ${ctx}: location.position must be a number`);
  }
}

export const adminApi = createApi({
  reducerPath: 'adminApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/admin',
    prepareHeaders: async (headers, { extra }) => {
      const { getTokenOrNull } = extra as AdminApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  tagTypes: [
    'AdminUsers',
    'AdminUsersStats',
    'AdminFeedback',
    'LocationHealth',
    'LocationIntegrity',
    'LocationAliases',
    'LocationProblemJobs',
  ],
  endpoints: (builder) => ({
    listAdminFeedback: builder.query<
      AdminFeedbackListResponse,
      AdminFeedbackPageArgs
    >({
      query: ({ page, rowsPerPage, sortDir }) =>
        `/feedback?limit=${rowsPerPage}&offset=${page * rowsPerPage}&sort_dir=${sortDir}`,
      transformResponse: (res: unknown): AdminFeedbackListResponse => {
        // Runtime guard mirroring listAdminUsers: a 2xx body with the wrong
        // shape (CDN error page, a missing field) would otherwise yield
        // ``undefined`` and silently render an empty table / wrong count.
        if (
          res == null ||
          typeof res !== 'object' ||
          !Array.isArray((res as { feedback?: unknown }).feedback) ||
          typeof (res as { total?: unknown }).total !== 'number'
        ) {
          throw new Error(
            'Invalid /api/admin/feedback response: missing feedback[] or total'
          );
        }
        const { feedback, total } = res as AdminFeedbackListResponse;
        return { feedback, total };
      },
      providesTags: ['AdminFeedback'],
    }),
    listAdminUsers: builder.query<AdminUserRow[], void>({
      query: () => '/users',
      transformResponse: (res: unknown): AdminUserRow[] => {
        // Runtime guard: catches the "proxy returns 2xx with the wrong
        // body" case (e.g. CDN error page misrouted, future server
        // wraps the envelope for pagination). Without this, the consumer
        // gets ``undefined`` and silently renders an empty roster — the
        // exact "silently zero admins" failure mode this PR exists to
        // prevent.
        //
        // ``res`` is typed ``unknown`` (not ``AdminUsersListResponse``)
        // because the body is UNTRUSTED at this boundary — the annotation
        // must say so. Matches the pattern ``getAdminUsersStats`` uses.
        if (
          res == null ||
          typeof res !== 'object' ||
          !Array.isArray((res as { users?: unknown }).users)
        ) {
          throw new Error(
            'Invalid /api/admin/users response: missing users[]'
          );
        }
        // Per-row guard: the roster reads ``visitCount`` as a number for the
        // Visits column + sort. A row missing it (serializer regression,
        // misrouted body) would render ``undefined`` and sort incorrectly —
        // surface it as a hard failure instead, matching the envelope check.
        for (const u of (res as { users: unknown[] }).users) {
          if (
            u == null ||
            typeof u !== 'object' ||
            typeof (u as { visitCount?: unknown }).visitCount !== 'number'
          ) {
            throw new Error(
              'Invalid /api/admin/users response: row missing numeric visitCount'
            );
          }
        }
        return (res as AdminUsersListResponse).users;
      },
      providesTags: ['AdminUsers'],
    }),
    getAdminUsersStats: builder.query<AdminUsersStats, void>({
      query: () => '/users/stats',
      transformResponse: (res: unknown): AdminUsersStats => {
        // Symmetric runtime guard to ``listAdminUsers`` — catches the
        // "proxy returns 2xx with the wrong body" case. Without this,
        // ``stats?.totalUsers ?? users.length`` in AdminUsersPage
        // silently falls back to the loaded-roster count and shows the
        // wrong "Total users" number with no error signal.
        if (!res || typeof res !== 'object') {
          throw new Error(
            'Invalid /api/admin/users/stats response: body is not an object'
          );
        }
        const obj = res as Record<string, unknown>;
        if (typeof obj.totalUsers !== 'number') {
          throw new Error(
            'Invalid /api/admin/users/stats response: missing or non-number totalUsers'
          );
        }
        if (
          obj.byProvider == null ||
          typeof obj.byProvider !== 'object' ||
          Array.isArray(obj.byProvider)
        ) {
          throw new Error(
            'Invalid /api/admin/users/stats response: missing or non-object byProvider'
          );
        }
        // Audit pass-3: validate that every value in ``byProvider`` is
        // a number. The Pydantic v2 boundary on the backend enforces
        // ``dict[SignupProvider, int]``, but a CDN error page or
        // future serializer that returns ``{ google: "5" }`` would
        // still slip past the previous "non-object" check and render
        // a string as a count.
        for (const v of Object.values(obj.byProvider as Record<string, unknown>)) {
          if (typeof v !== 'number') {
            throw new Error(
              'Invalid /api/admin/users/stats response: byProvider contains a non-number value'
            );
          }
        }
        // Audit pass-3: the timestamp fields are ``string | null`` by
        // contract. A numeric timestamp (e.g. ``0`` from a misconfigured
        // serializer) must reject — otherwise downstream
        // ``new Date(iso).getTime()`` would silently produce
        // "1970-01-01" or NaN.
        if (
          obj.firstSignupAt !== null &&
          obj.firstSignupAt !== undefined &&
          typeof obj.firstSignupAt !== 'string'
        ) {
          throw new Error(
            'Invalid /api/admin/users/stats response: firstSignupAt must be string or null'
          );
        }
        if (
          obj.latestSignupAt !== null &&
          obj.latestSignupAt !== undefined &&
          typeof obj.latestSignupAt !== 'string'
        ) {
          throw new Error(
            'Invalid /api/admin/users/stats response: latestSignupAt must be string or null'
          );
        }
        return obj as unknown as AdminUsersStats;
      },
      providesTags: ['AdminUsersStats'],
    }),
    grantAdmin: builder.mutation<void, { userId: string }>({
      query: ({ userId }) => ({
        url: `/users/${userId}/admin`,
        method: 'POST',
      }),
      invalidatesTags: ['AdminUsers', 'AdminUsersStats'],
    }),
    revokeAdmin: builder.mutation<void, { userId: string }>({
      query: ({ userId }) => ({
        url: `/users/${userId}/admin`,
        method: 'DELETE',
      }),
      invalidatesTags: ['AdminUsers', 'AdminUsersStats'],
    }),

    // ─── Location Normalization Monitor ─────────────────────────────────────

    getLocationHealth: builder.query<LocationHealth, void>({
      query: () => '/locations/health',
      transformResponse: (res: unknown): LocationHealth => {
        // Throwing guard (hard house rule): a proxy 2xx with the wrong body
        // (CDN error page, future serializer change) must surface as an
        // error, never silently render a fabricated "verdict" from
        // undefined fields. Validate every field the verdict logic reads.
        if (!isRecord(res)) {
          throw new Error('Invalid /api/admin/locations/health response: body is not an object');
        }
        for (const field of [
          'windowHours',
          'nullBacklog',
          'nullAged',
          'done',
          'failed',
          'total',
          'failedBlank',
          'failedNonblank',
          'failedNonblankRatio',
        ] as const) {
          if (typeof res[field] !== 'number') {
            throw new Error(
              `Invalid /api/admin/locations/health response: ${field} must be a number`
            );
          }
        }
        for (const field of ['schemaPresent', 'keyConfigured', 'dormant'] as const) {
          if (typeof res[field] !== 'boolean') {
            throw new Error(
              `Invalid /api/admin/locations/health response: ${field} must be a boolean`
            );
          }
        }
        if (res.heartbeatAgeMinutes !== null && typeof res.heartbeatAgeMinutes !== 'number') {
          throw new Error(
            'Invalid /api/admin/locations/health response: heartbeatAgeMinutes must be number or null'
          );
        }
        if (res.throughputInWindow !== null && typeof res.throughputInWindow !== 'number') {
          throw new Error(
            'Invalid /api/admin/locations/health response: throughputInWindow must be number or null'
          );
        }
        if (!isRecord(res.normalizeQueue)) {
          throw new Error(
            'Invalid /api/admin/locations/health response: normalizeQueue must be an object'
          );
        }
        for (const v of Object.values(res.normalizeQueue)) {
          if (typeof v !== 'number') {
            throw new Error(
              'Invalid /api/admin/locations/health response: normalizeQueue contains a non-number value'
            );
          }
        }
        return res as unknown as LocationHealth;
      },
      providesTags: ['LocationHealth'],
    }),

    getLocationIntegrity: builder.query<IntegrityCheck[], void>({
      query: () => '/locations/integrity',
      transformResponse: (res: unknown): IntegrityCheck[] => {
        if (!isRecord(res)) {
          throw new Error('Invalid /api/admin/locations/integrity response: body is not an object');
        }
        if (typeof res.schemaPresent !== 'boolean') {
          throw new Error(
            'Invalid /api/admin/locations/integrity response: schemaPresent must be a boolean'
          );
        }
        if (!Array.isArray(res.checks)) {
          throw new Error(
            'Invalid /api/admin/locations/integrity response: checks must be an array'
          );
        }
        for (const check of res.checks) {
          if (!isRecord(check)) {
            throw new Error(
              'Invalid /api/admin/locations/integrity response: check entry is not an object'
            );
          }
          if (typeof check.id !== 'string' || typeof check.label !== 'string') {
            throw new Error(
              'Invalid /api/admin/locations/integrity response: check.id and check.label must be strings'
            );
          }
          if (typeof check.count !== 'number') {
            throw new Error(
              'Invalid /api/admin/locations/integrity response: check.count must be a number'
            );
          }
          if (!isIntegritySeverity(check.severity)) {
            throw new Error(
              'Invalid /api/admin/locations/integrity response: check.severity must be ok|warn|crit'
            );
          }
        }
        return (res as unknown as IntegrityResponse).checks;
      },
      providesTags: ['LocationIntegrity'],
    }),

    listLocationAliases: builder.query<
      AliasListResponse,
      { contains?: string; limit: number; offset: number }
    >({
      query: ({ contains, limit, offset }) => ({
        url: '/locations/aliases',
        // Omit ``contains`` entirely when empty so the backend serves the
        // unfiltered page rather than filtering on an empty string.
        params: {
          ...(contains && contains.length > 0 ? { contains } : {}),
          limit,
          offset,
        },
      }),
      transformResponse: (res: unknown): AliasListResponse => {
        if (!isRecord(res)) {
          throw new Error('Invalid /api/admin/locations/aliases response: body is not an object');
        }
        if (typeof res.total !== 'number') {
          throw new Error('Invalid /api/admin/locations/aliases response: total must be a number');
        }
        if (!Array.isArray(res.aliases)) {
          throw new Error('Invalid /api/admin/locations/aliases response: aliases must be an array');
        }
        for (const alias of res.aliases) {
          if (!isRecord(alias)) {
            throw new Error(
              'Invalid /api/admin/locations/aliases response: alias entry is not an object'
            );
          }
          if (typeof alias.rawText !== 'string') {
            throw new Error(
              'Invalid /api/admin/locations/aliases response: alias.rawText must be a string'
            );
          }
          if (!isAliasSource(alias.source)) {
            throw new Error(
              'Invalid /api/admin/locations/aliases response: alias.source must be llm|manual'
            );
          }
          if (alias.confidence !== null && typeof alias.confidence !== 'number') {
            throw new Error(
              'Invalid /api/admin/locations/aliases response: alias.confidence must be number or null'
            );
          }
          if (!Array.isArray(alias.locations)) {
            throw new Error(
              'Invalid /api/admin/locations/aliases response: alias.locations must be an array'
            );
          }
          for (const loc of alias.locations) {
            validateCanonicalLocation(loc, '/api/admin/locations/aliases response', true);
          }
        }
        return res as unknown as AliasListResponse;
      },
      providesTags: ['LocationAliases'],
    }),

    reverseSearchLocations: builder.query<
      ReverseSearchResponse,
      { contains?: string; limit: number }
    >({
      query: ({ contains, limit }) => ({
        url: '/locations/reverse',
        params: {
          ...(contains && contains.length > 0 ? { contains } : {}),
          limit,
        },
      }),
      transformResponse: (res: unknown): ReverseSearchResponse => {
        if (!isRecord(res)) {
          throw new Error('Invalid /api/admin/locations/reverse response: body is not an object');
        }
        if (!Array.isArray(res.results)) {
          throw new Error('Invalid /api/admin/locations/reverse response: results must be an array');
        }
        for (const result of res.results) {
          if (!isRecord(result)) {
            throw new Error(
              'Invalid /api/admin/locations/reverse response: result entry is not an object'
            );
          }
          validateCanonicalLocation(result.location, '/api/admin/locations/reverse response', false);
          if (
            !Array.isArray(result.rawTexts) ||
            result.rawTexts.some((t) => typeof t !== 'string')
          ) {
            throw new Error(
              'Invalid /api/admin/locations/reverse response: result.rawTexts must be a string array'
            );
          }
        }
        return res as unknown as ReverseSearchResponse;
      },
      providesTags: ['LocationAliases'],
    }),

    getAliasOriginals: builder.query<AliasOriginalsResponse, { rawText: string; limit: number }>({
      query: ({ rawText, limit }) => ({
        url: '/locations/alias-originals',
        params: { rawText, limit },
      }),
      transformResponse: (res: unknown): AliasOriginalsResponse => {
        if (!isRecord(res)) {
          throw new Error(
            'Invalid /api/admin/locations/alias-originals response: body is not an object'
          );
        }
        if (typeof res.rawText !== 'string') {
          throw new Error(
            'Invalid /api/admin/locations/alias-originals response: rawText must be a string'
          );
        }
        if (typeof res.total !== 'number') {
          throw new Error(
            'Invalid /api/admin/locations/alias-originals response: total must be a number'
          );
        }
        if (!Array.isArray(res.originals)) {
          throw new Error(
            'Invalid /api/admin/locations/alias-originals response: originals must be an array'
          );
        }
        for (const original of res.originals) {
          if (!isRecord(original)) {
            throw new Error(
              'Invalid /api/admin/locations/alias-originals response: original entry is not an object'
            );
          }
          if (typeof original.original !== 'string') {
            throw new Error(
              'Invalid /api/admin/locations/alias-originals response: original.original must be a string'
            );
          }
          if (
            !Array.isArray(original.jobIds) ||
            original.jobIds.some((j) => typeof j !== 'string')
          ) {
            throw new Error(
              'Invalid /api/admin/locations/alias-originals response: original.jobIds must be a string array'
            );
          }
        }
        return res as unknown as AliasOriginalsResponse;
      },
      providesTags: ['LocationAliases'],
    }),

    listProblemJobs: builder.query<ProblemJobsResponse, { limit: number; offset: number }>({
      query: ({ limit, offset }) => ({
        url: '/locations/problem-jobs',
        params: { limit, offset },
      }),
      transformResponse: (res: unknown): ProblemJobsResponse => {
        if (!isRecord(res)) {
          throw new Error(
            'Invalid /api/admin/locations/problem-jobs response: body is not an object'
          );
        }
        if (typeof res.total !== 'number') {
          throw new Error(
            'Invalid /api/admin/locations/problem-jobs response: total must be a number'
          );
        }
        if (!Array.isArray(res.jobs)) {
          throw new Error(
            'Invalid /api/admin/locations/problem-jobs response: jobs must be an array'
          );
        }
        for (const job of res.jobs) {
          if (!isRecord(job)) {
            throw new Error(
              'Invalid /api/admin/locations/problem-jobs response: job entry is not an object'
            );
          }
          if (typeof job.id !== 'string') {
            throw new Error(
              'Invalid /api/admin/locations/problem-jobs response: job.id must be a string'
            );
          }
          for (const field of [
            'title',
            'company',
            'location',
            'normalizationStatus',
            'lastSeenAt',
          ] as const) {
            const val = job[field];
            if (val !== null && val !== undefined && typeof val !== 'string') {
              throw new Error(
                `Invalid /api/admin/locations/problem-jobs response: job.${field} must be string or null`
              );
            }
          }
        }
        return res as unknown as ProblemJobsResponse;
      },
      providesTags: ['LocationProblemJobs'],
    }),

    overrideAlias: builder.mutation<unknown, { rawText: string; locations: LocationSpec[] }>({
      query: ({ rawText, locations }) => ({
        // ``rawText`` may contain a literal ``/`` (e.g. "Remote / US") which
        // can break path routing through the proxy — encode it. If the proxy
        // still rejects, the caller surfaces extractErrorMessage rather than
        // swallowing it.
        url: `/locations/aliases/${encodeURIComponent(rawText)}`,
        method: 'PUT',
        body: { locations },
      }),
      invalidatesTags: ['LocationAliases', 'LocationIntegrity', 'LocationHealth'],
    }),

    renormalizeJob: builder.mutation<unknown, { jobId: string }>({
      query: ({ jobId }) => ({
        url: `/jobs/${jobId}/normalize`,
        method: 'POST',
      }),
      invalidatesTags: ['LocationProblemJobs', 'LocationHealth'],
    }),
  }),
});

export const {
  useListAdminFeedbackQuery,
  useListAdminUsersQuery,
  useGetAdminUsersStatsQuery,
  useGrantAdminMutation,
  useRevokeAdminMutation,
  useGetLocationHealthQuery,
  useGetLocationIntegrityQuery,
  useListLocationAliasesQuery,
  useReverseSearchLocationsQuery,
  useGetAliasOriginalsQuery,
  useListProblemJobsQuery,
  useOverrideAliasMutation,
  useRenormalizeJobMutation,
} = adminApi;
