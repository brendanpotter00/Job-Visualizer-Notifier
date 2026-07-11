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
 * One user's individual visit history, for the roster's clickable Visits modal
 * (``GET /api/admin/users/{id}/visits``). ``visits`` is most-recent-first ISO
 * timestamps, capped server-side. ``totalVisitCount`` is the denormalized
 * ``visitCount`` so the modal can flag the count-vs-history gap (per-visit
 * history only began when the backend started logging, so it can be shorter
 * than the count). ``truncated`` is true when the list hit the server cap.
 */
export interface AdminUserVisitsResponse {
  visits: string[];
  totalVisitCount: number;
  truncated: boolean;
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

// --- Enrichment pipeline oversight types ---------------------------------

/** GET /api/admin/enrichment/health response. */
export interface EnrichmentHealth {
  schemaPresent: boolean;
  enabled: boolean;
  /** OPEN jobs by enrichment bucket: unenriched | claimed | done | needs_human. */
  openByStatus: Record<string, number>;
  /** Unenriched OPEN rows /pending could actually hand out. */
  eligibleUnenriched: number;
  staleClaims: number;
  claimTtlMinutes: number;
  /** Actionable queue depth: OPEN + not yet human-corrected. */
  needsHumanOpen: number;
  humanCorrectedTotal: number;
  lastEnrichedAt: string | null;
  lastEnrichedAgeS: number | null;
  lastTickUuid: string | null;
  lastTickStatus: string | null;
  lastTickStartedAt: string | null;
  lastTickAgeS: number | null;
  lastTickDriftSuspected: boolean;
  windowHours: number;
  enrichedInWindow: number;
  errorTicksInWindow: number;
}

/**
 * The fields the correction editor needs from a row — the structural subset
 * shared by the needs-human queue and the recent-enrichments table, so any
 * row an admin can see is also a row they can correct.
 */
export interface EnrichmentCorrectionTarget {
  sourceId: string;
  jobListingId: string;
  title: string | null;
  company: string | null;
  category: string | null;
  level: string | null;
  tags: string[];
  classifyConfidence: number | null;
  classifyReasoning: string | null;
  judgeNotes: string | null;
}

/** One needs-human queue row. */
export interface EnrichmentNeedsHumanRow {
  sourceId: string;
  jobListingId: string;
  title: string | null;
  company: string | null;
  url: string | null;
  jobStatus: string | null;
  enrichmentStatus: string | null;
  category: string | null;
  level: string | null;
  tags: string[];
  cleanDescription: string | null;
  classifyConfidence: number | null;
  classifyReasoning: string | null;
  taxonomyVersion: string | null;
  judged: boolean;
  judgePassed: boolean | null;
  judgeConfidence: number | null;
  judgeNotes: string | null;
  enrichedAt: string | null;
  humanCorrectedAt: string | null;
  humanCorrectedBy: string | null;
  /** NULL not reviewed | 'corrected' | 'confirmed_correct'. */
  humanDecision: string | null;
}

export interface EnrichmentNeedsHumanResponse {
  rows: EnrichmentNeedsHumanRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnrichmentNeedsHumanArgs {
  limit: number;
  offset: number;
  company?: string;
  category?: string;
  level?: string;
  includeCorrected?: boolean;
  onlyOpen?: boolean;
}

/** One pushed enricher tick. */
export interface EnrichmentTickRow {
  tickUuid: string;
  startedAt: string;
  endedAt: string | null;
  status: string;
  notes: string | null;
  claimed: number;
  cleaned: number;
  classified: number;
  judged: number;
  corrected: number;
  needsHuman: number;
  sent: number;
  errors: number;
  nulledFacets: number;
  durationS: number | null;
  taxonomyVersion: string | null;
  stageTimings: { stage: string; ms: number; items: number; retries: number }[] | null;
  heartbeatAgeS: number | null;
  driftSuspected: boolean;
  receivedAt: string | null;
}

export interface EnrichmentTicksResponse {
  ticks: EnrichmentTickRow[];
  windowHours: number;
  latestScorecard: Record<string, unknown> | null;
  latestScorecardTickUuid: string | null;
  latestKnobs: Record<string, unknown> | null;
}

/** One recently-enriched job. */
export interface EnrichmentRecentRow {
  sourceId: string;
  jobListingId: string;
  title: string | null;
  company: string | null;
  url: string | null;
  enrichmentStatus: string | null;
  category: string | null;
  level: string | null;
  tags: string[];
  classifyConfidence: number | null;
  classifyReasoning: string | null;
  judged: boolean;
  judgePassed: boolean | null;
  judgeConfidence: number | null;
  judgeNotes: string | null;
  taxonomyVersion: string | null;
  needsHuman: boolean;
  humanCorrectedAt: string | null;
  /** NULL not reviewed | 'corrected' | 'confirmed_correct'. */
  humanDecision: string | null;
  enrichedAt: string | null;
}

/** POST .../correct request body. */
export interface EnrichmentCorrectionRequest {
  category: string | null;
  level: string | null;
  tags: string[];
  note?: string | null;
}

/** Correction / re-enrich response. */
export interface EnrichmentCorrectionResult {
  sourceId: string;
  jobListingId: string;
  enrichmentStatus: string | null;
  category: string | null;
  level: string | null;
  tags: string[];
  humanCorrectedAt: string | null;
  humanCorrectedBy: string | null;
  /** NULL not reviewed | 'corrected' | 'confirmed_correct'. */
  humanDecision: string | null;
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
    'AdminUserVisits',
    'AdminFeedback',
    'LocationHealth',
    'LocationIntegrity',
    'LocationAliases',
    'LocationProblemJobs',
    'EnrichmentHealth',
    'EnrichmentNeedsHuman',
    'EnrichmentTicks',
    'EnrichmentRecent',
  ],
  endpoints: (builder) => ({
    listAdminFeedback: builder.query<AdminFeedbackListResponse, AdminFeedbackPageArgs>({
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
          throw new Error('Invalid /api/admin/feedback response: missing feedback[] or total');
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
          throw new Error('Invalid /api/admin/users response: missing users[]');
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
            throw new Error('Invalid /api/admin/users response: row missing numeric visitCount');
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
          throw new Error('Invalid /api/admin/users/stats response: body is not an object');
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
    getUserVisits: builder.query<AdminUserVisitsResponse, { userId: string }>({
      // ``userId`` is a uuid hex with no ``/`` today, but encode defensively
      // (matches ``overrideAlias``) so a future id format can't break routing.
      query: ({ userId }) => `/users/${encodeURIComponent(userId)}/visits`,
      transformResponse: (res: unknown): AdminUserVisitsResponse => {
        // Throwing runtime guard, mirroring listAdminUsers / getAdminUsersStats:
        // a 2xx body with the wrong shape (CDN error page, serializer drift)
        // must surface as an error, not render a fabricated empty history.
        if (!isRecord(res)) {
          throw new Error('Invalid /api/admin/users/{id}/visits response: body is not an object');
        }
        if (!Array.isArray(res.visits) || res.visits.some((v) => typeof v !== 'string')) {
          throw new Error('Invalid user visits response: visits must be a string[]');
        }
        if (typeof res.totalVisitCount !== 'number') {
          throw new Error('Invalid user visits response: totalVisitCount must be a number');
        }
        if (typeof res.truncated !== 'boolean') {
          throw new Error('Invalid user visits response: truncated must be a boolean');
        }
        return {
          visits: res.visits as string[],
          totalVisitCount: res.totalVisitCount,
          truncated: res.truncated,
        };
      },
      // Per-user cache entry (RTK Query keys by the serialized arg).
      providesTags: (_result, _error, { userId }) => [{ type: 'AdminUserVisits', id: userId }],
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
          throw new Error(
            'Invalid /api/admin/locations/aliases response: aliases must be an array'
          );
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
          throw new Error(
            'Invalid /api/admin/locations/reverse response: results must be an array'
          );
        }
        for (const result of res.results) {
          if (!isRecord(result)) {
            throw new Error(
              'Invalid /api/admin/locations/reverse response: result entry is not an object'
            );
          }
          validateCanonicalLocation(
            result.location,
            '/api/admin/locations/reverse response',
            false
          );
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

    // --- Enrichment pipeline oversight -----------------------------------

    getEnrichmentHealth: builder.query<EnrichmentHealth, { windowHours?: number } | void>({
      query: (args) => ({
        url: '/enrichment/health',
        params: args && args.windowHours ? { windowHours: args.windowHours } : undefined,
      }),
      transformResponse: (res: unknown): EnrichmentHealth => {
        // Throwing guard (hard house rule): the verdict banner must never be
        // computed from undefined fields of a wrong-shaped 2xx body.
        if (!isRecord(res)) {
          throw new Error('Invalid /api/admin/enrichment/health response: body is not an object');
        }
        for (const field of [
          'eligibleUnenriched',
          'staleClaims',
          'claimTtlMinutes',
          'needsHumanOpen',
          'humanCorrectedTotal',
          'windowHours',
          'enrichedInWindow',
          'errorTicksInWindow',
        ] as const) {
          if (typeof res[field] !== 'number') {
            throw new Error(
              `Invalid /api/admin/enrichment/health response: ${field} must be a number`
            );
          }
        }
        for (const field of ['schemaPresent', 'enabled', 'lastTickDriftSuspected'] as const) {
          if (typeof res[field] !== 'boolean') {
            throw new Error(
              `Invalid /api/admin/enrichment/health response: ${field} must be a boolean`
            );
          }
        }
        if (!isRecord(res.openByStatus)) {
          throw new Error(
            'Invalid /api/admin/enrichment/health response: openByStatus must be an object'
          );
        }
        for (const v of Object.values(res.openByStatus)) {
          if (typeof v !== 'number') {
            throw new Error(
              'Invalid /api/admin/enrichment/health response: openByStatus contains a non-number'
            );
          }
        }
        for (const field of ['lastEnrichedAgeS', 'lastTickAgeS'] as const) {
          if (res[field] !== null && typeof res[field] !== 'number') {
            throw new Error(
              `Invalid /api/admin/enrichment/health response: ${field} must be number or null`
            );
          }
        }
        return res as unknown as EnrichmentHealth;
      },
      providesTags: ['EnrichmentHealth'],
    }),

    listEnrichmentNeedsHuman: builder.query<EnrichmentNeedsHumanResponse, EnrichmentNeedsHumanArgs>(
      {
        query: ({ limit, offset, company, category, level, includeCorrected, onlyOpen }) => ({
          url: '/enrichment/needs-human',
          params: {
            limit,
            offset,
            ...(company ? { company } : {}),
            ...(category ? { category } : {}),
            ...(level ? { level } : {}),
            ...(includeCorrected ? { includeCorrected } : {}),
            ...(onlyOpen === false ? { onlyOpen } : {}),
          },
        }),
        transformResponse: (res: unknown): EnrichmentNeedsHumanResponse => {
          // Throwing guard (mirrors the thorough location guards above): the only
          // ErrorBoundary is app-root, so a render throw here blanks the whole
          // SPA. Validate every render-critical value field per its DECLARED type
          // so a wrong-shaped 2xx surfaces as a localized ErrorState, not a
          // ``.toFixed is not a function`` / Invalid-Date crash in the table.
          if (!isRecord(res) || !Array.isArray(res.rows) || typeof res.total !== 'number') {
            throw new Error('Invalid /api/admin/enrichment/needs-human response');
          }
          for (const row of res.rows) {
            if (
              !isRecord(row) ||
              typeof row.jobListingId !== 'string' ||
              typeof row.sourceId !== 'string'
            ) {
              throw new Error('Invalid /api/admin/enrichment/needs-human response: malformed row');
            }
            if (!Array.isArray(row.tags)) {
              throw new Error(
                'Invalid /api/admin/enrichment/needs-human response: tags must be an array'
              );
            }
            // Confidences render via ``.toFixed(2)`` behind only a ``!= null``
            // check — a stringified number ("0.5") would crash the row.
            for (const field of ['classifyConfidence', 'judgeConfidence'] as const) {
              const val = row[field];
              if (val !== null && val !== undefined && typeof val !== 'number') {
                throw new Error(
                  `Invalid /api/admin/enrichment/needs-human response: ${field} must be number or null`
                );
              }
            }
            // Every ``string | null`` field the NeedsHumanTable renders as a
            // React child. An object value in any of them is an "Objects are not
            // valid as a React child" (or Invalid-Date) crash — and the only
            // ErrorBoundary is app-root, so it blanks the whole SPA. ``title``/
            // ``company``/``url`` render directly (title as text, url into a
            // <Link href>); ``enrichedAt`` feeds ``new Date(...)`` in the
            // Enriched column; ``cleanDescription`` renders in the expander +
            // full-description dialog; ``category``/``level`` render as Chip
            // labels (``FACET_LABELS[slug] ?? slug`` — an object slug keys to
            // undefined then falls through to the raw object);
            // ``classifyReasoning``/``judgeNotes`` render as expander text;
            // ``taxonomyVersion`` renders as ``taxonomy {v ?? '—'}`` footer text.
            // (``jobStatus``/``enrichmentStatus`` are intentionally NOT validated
            // per Ledger #1 — forward-compat status strings consumed via ``===``.)
            for (const field of [
              'title',
              'company',
              'url',
              'cleanDescription',
              'enrichedAt',
              'category',
              'level',
              'classifyReasoning',
              'judgeNotes',
              'taxonomyVersion',
            ] as const) {
              const val = row[field];
              if (val !== null && val !== undefined && typeof val !== 'string') {
                throw new Error(
                  `Invalid /api/admin/enrichment/needs-human response: ${field} must be string or null`
                );
              }
            }
          }
          return res as unknown as EnrichmentNeedsHumanResponse;
        },
        providesTags: ['EnrichmentNeedsHuman'],
      }
    ),

    getEnrichmentTicks: builder.query<EnrichmentTicksResponse, { windowHours?: number } | void>({
      query: (args) => ({
        url: '/enrichment/ticks',
        params: args && args.windowHours ? { windowHours: args.windowHours } : undefined,
      }),
      transformResponse: (res: unknown): EnrichmentTicksResponse => {
        if (!isRecord(res) || !Array.isArray(res.ticks) || typeof res.windowHours !== 'number') {
          throw new Error('Invalid /api/admin/enrichment/ticks response');
        }
        // ``latestScorecardTickUuid`` is an envelope-level ``string | null`` that
        // ScorecardPanel renders directly (``from tick {scorecardTickUuid}``) — an
        // object value is an "Objects are not valid as a React child" whole-SPA
        // crash via the app-root ErrorBoundary.
        if (
          res.latestScorecardTickUuid !== null &&
          res.latestScorecardTickUuid !== undefined &&
          typeof res.latestScorecardTickUuid !== 'string'
        ) {
          throw new Error(
            'Invalid /api/admin/enrichment/ticks response: latestScorecardTickUuid must be string or null'
          );
        }
        for (const tick of res.ticks) {
          // ``startedAt`` feeds ``format(new Date(t.startedAt))`` in TickCharts'
          // two useMemos — a missing/non-string value yields an Invalid Date →
          // date-fns ``format`` ``RangeError`` in render, which the app-root
          // ErrorBoundary turns into a whole-SPA blank. (A number would instead
          // render a wrong epoch-ms date, not crash — so we reject non-strings.)
          if (
            !isRecord(tick) ||
            typeof tick.tickUuid !== 'string' ||
            typeof tick.status !== 'string' ||
            typeof tick.startedAt !== 'string'
          ) {
            throw new Error('Invalid /api/admin/enrichment/ticks response: malformed tick');
          }
          // ``stageTimings`` (``{ stage; ms; items; retries }[] | null``) feeds
          // ``t.stageTimings?.find((s) => s.stage === stage)`` in a TickCharts
          // useMemo — a truthy NON-array value is a ``.find is not a function``
          // crash in render (whole-SPA blank via the app-root ErrorBoundary).
          if (tick.stageTimings != null && !Array.isArray(tick.stageTimings)) {
            throw new Error(
              'Invalid /api/admin/enrichment/ticks response: stageTimings must be an array or null'
            );
          }
          // ``notes`` renders directly as a React child in TickStrip's per-tick
          // tooltip (``{tick.notes && <div>{tick.notes}</div>}``) — a truthy
          // object value is an "Objects are not valid as a React child" whole-SPA
          // crash. ``string | null`` by contract. (``status`` is a required
          // string already asserted above; per Ledger #1 it is NOT union-checked.)
          if (tick.notes !== null && tick.notes !== undefined && typeof tick.notes !== 'string') {
            throw new Error(
              'Invalid /api/admin/enrichment/ticks response: notes must be string or null'
            );
          }
        }
        return res as unknown as EnrichmentTicksResponse;
      },
      providesTags: ['EnrichmentTicks'],
    }),

    getEnrichmentRecent: builder.query<EnrichmentRecentRow[], { limit?: number } | void>({
      query: (args) => ({
        url: '/enrichment/recent',
        params: args && args.limit ? { limit: args.limit } : undefined,
      }),
      transformResponse: (res: unknown): EnrichmentRecentRow[] => {
        if (!isRecord(res) || !Array.isArray(res.rows)) {
          throw new Error('Invalid /api/admin/enrichment/recent response');
        }
        for (const row of res.rows) {
          if (
            !isRecord(row) ||
            typeof row.jobListingId !== 'string' ||
            typeof row.sourceId !== 'string'
          ) {
            throw new Error('Invalid /api/admin/enrichment/recent response: malformed row');
          }
          // RecentEnrichmentsTable reads ``row.tags.slice(0, 3)`` / ``.length``
          // unconditionally — a non-array is an unguarded ``TypeError`` in
          // render (whole-SPA crash via the app-root ErrorBoundary).
          if (!Array.isArray(row.tags)) {
            throw new Error('Invalid /api/admin/enrichment/recent response: tags must be an array');
          }
          // Confidences render via ``.toFixed(2)`` behind only a ``!= null``
          // check; a stringified number would crash the row.
          for (const field of ['classifyConfidence', 'judgeConfidence'] as const) {
            const val = row[field];
            if (val !== null && val !== undefined && typeof val !== 'number') {
              throw new Error(
                `Invalid /api/admin/enrichment/recent response: ${field} must be number or null`
              );
            }
          }
          // Every ``string | null`` field RecentEnrichmentsTable renders as a
          // React child (app-root is the only ErrorBoundary, so any object value
          // blanks the whole SPA). ``enrichedAt`` feeds ``new Date(...)``;
          // ``title``/``company``/``url`` render directly (url into an <a href>);
          // ``category``/``level`` render as Chip labels
          // (``FACET_LABELS[slug] ?? slug`` falls through to the raw object for a
          // non-string slug); ``classifyReasoning``/``judgeNotes`` render as
          // expander text; ``taxonomyVersion`` renders as ``taxonomy {v ?? '—'}``.
          // (``enrichmentStatus`` is intentionally NOT validated per Ledger #1.)
          for (const field of [
            'title',
            'company',
            'url',
            'enrichedAt',
            'category',
            'level',
            'classifyReasoning',
            'judgeNotes',
            'taxonomyVersion',
          ] as const) {
            const val = row[field];
            if (val !== null && val !== undefined && typeof val !== 'string') {
              throw new Error(
                `Invalid /api/admin/enrichment/recent response: ${field} must be string or null`
              );
            }
          }
        }
        return res.rows as unknown as EnrichmentRecentRow[];
      },
      providesTags: ['EnrichmentRecent'],
    }),

    correctEnrichment: builder.mutation<
      EnrichmentCorrectionResult,
      { sourceId: string; jobListingId: string; body: EnrichmentCorrectionRequest }
    >({
      query: ({ sourceId, jobListingId, body }) => ({
        url: `/enrichment/jobs/${encodeURIComponent(sourceId)}/${encodeURIComponent(jobListingId)}/correct`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['EnrichmentNeedsHuman', 'EnrichmentHealth', 'EnrichmentRecent'],
    }),

    // One-click "this is correct": keeps the enricher's proposed labels, clears
    // needs-human, and stamps human_decision='confirmed_correct'. No body — the
    // whole point is zero friction versus the Correct dialog.
    confirmEnrichment: builder.mutation<
      EnrichmentCorrectionResult,
      { sourceId: string; jobListingId: string }
    >({
      query: ({ sourceId, jobListingId }) => ({
        url: `/enrichment/jobs/${encodeURIComponent(sourceId)}/${encodeURIComponent(jobListingId)}/confirm`,
        method: 'POST',
      }),
      invalidatesTags: ['EnrichmentNeedsHuman', 'EnrichmentHealth', 'EnrichmentRecent'],
    }),

    reenrichEnrichmentJob: builder.mutation<
      EnrichmentCorrectionResult,
      { sourceId: string; jobListingId: string }
    >({
      query: ({ sourceId, jobListingId }) => ({
        url: `/enrichment/jobs/${encodeURIComponent(sourceId)}/${encodeURIComponent(jobListingId)}/reenrich`,
        method: 'POST',
      }),
      invalidatesTags: ['EnrichmentNeedsHuman', 'EnrichmentHealth', 'EnrichmentRecent'],
    }),
  }),
});

export const {
  useListAdminFeedbackQuery,
  useListAdminUsersQuery,
  useGetAdminUsersStatsQuery,
  useGetUserVisitsQuery,
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
  useGetEnrichmentHealthQuery,
  useListEnrichmentNeedsHumanQuery,
  useGetEnrichmentTicksQuery,
  useGetEnrichmentRecentQuery,
  useCorrectEnrichmentMutation,
  useConfirmEnrichmentMutation,
  useReenrichEnrichmentJobMutation,
} = adminApi;
