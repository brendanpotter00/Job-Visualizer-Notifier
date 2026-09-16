import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

// The admin Custom Companies page renders the SAME 5-rung discovery checklist
// the user-facing My Companies page does, off the same
// `provider_config->'discovery'->'steps'` blob. Reusing the type (rather than
// declaring a second wire-identical one) is what makes a backend rename a
// compile error in both places at once.
import type { DiscoveryStep } from '../userCompanies/userCompaniesApi';

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

// ───────────────────────────────────────────────────────────────────────────
// Custom Companies (E7) — admin oversight types
//
// Two GET endpoints back one read-only page: `/custom-companies` (the boards
// users added themselves + the four headline counts) and
// `/custom-companies/attempts` (one row per ADD ATTEMPT, plus the per-user
// rollup). Both are server-paginated like `listAdminFeedback` — `limit` /
// `offset` in, `total` out — because `company_add_attempts` is append-only and
// is the one table here that grows with every user submission.
//
// The aggregates (`summary`, `byOutcome`, `users`) are ALWAYS computed over the
// whole table, never the filtered page: the User dropdown is fed from the
// rollup, so it must not shrink as you filter by user.
// ───────────────────────────────────────────────────────────────────────────

/**
 * Is this custom scraper actually harvesting? Derived server-side from ONE SQL
 * CASE (never re-derived on the client) so the page and the StatTile can never
 * disagree. Precedence is top-down: `orphan` beats everything, because a board
 * with no owner row is a data-integrity problem whether or not it harvests.
 */
export type CustomCompanyLiveStatus =
  /** No `user_companies` row at all. */
  | 'orphan'
  /** No `company_harvests` row at all. */
  | 'never_harvested'
  /** enabled=false, OR newest verdict FAILED, OR 0 records harvested. */
  | 'failing'
  /** Newest harvest older than 2 x cadence_hours. */
  | 'stale'
  /** Enabled, non-FAILED, >0 records, inside 2 x cadence. */
  | 'live';

/** One user-added board (`companies.visibility = 'user'`). */
export interface AdminCustomCompanyRow {
  /** `companies.id`, e.g. 'u-pxfm7e08i4'. */
  id: string;
  displayName: string;
  /** 'discovered' | 'workday' | … */
  ats: string;
  boardToken: string;
  enabled: boolean;
  /** discovering | unverified | healthy | quarantined | refused. */
  healthState: string | null;
  cadenceHours: number | null;
  createdAt: string;
  lastSuccessAt: string | null;
  consecutiveFailures: number;

  // Owner — LEFT JOIN. ``ownerCount === 0`` is a real, present state (an
  // orphaned board), not a serialization bug.
  ownerUserId: string | null;
  ownerEmail: string | null;
  ownerDisplayName: string | null;
  /** > 1 means a shared board. */
  ownerCount: number;

  // company_scripts — LEFT JOIN; all null before the first script is written.
  /** 'http_json' | 'browser_fetch'. */
  transport: string | null;
  oracleKind: string | null;
  scriptVersion: number | null;

  // Newest company_harvests row — LEFT JOIN; all null when never harvested.
  /** ISO (= `company_harvests.started_at`). */
  lastHarvestAt: string | null;
  /** Server-computed seconds; render with `formatAge()`. */
  lastHarvestAgeS: number | null;
  /** 'VERIFIED' | 'UNVERIFIED' | 'FAILED'. */
  verdict: string | null;
  verdictReason: string | null;
  recordsHarvested: number | null;
  declaredTotal: number | null;
  oracleTotal: number | null;
  capHit: boolean | null;

  liveStatus: CustomCompanyLiveStatus;
  /** Short human reason the row is not live. null IFF liveStatus === 'live'. */
  liveReason: string | null;
}

/** The four headline counts, always over the WHOLE table (never the page). */
export interface AdminCustomCompaniesSummary {
  /** Every `visibility='user'` row. */
  trackedCount: number;
  liveCount: number;
  byLiveStatus: Partial<Record<CustomCompanyLiveStatus, number>>;
  /** health_state -> count. Key '' means a NULL health_state. */
  byHealthState: Record<string, number>;

  /** Distinct attempts, ALL TIME (not a 30-day window). */
  attemptCount: number;
  /** Distinct `user_id` that has ever submitted. */
  userCount: number;
  /** refused + unsupported + empty + probe_failed + stuck. */
  failedCount: number;
  refusedCount: number;
  stuckCount: number;
}

export interface AdminCustomCompaniesResponse {
  companies: AdminCustomCompanyRow[];
  /** Rows matching the filters, BEFORE limit/offset. Drives the pager. */
  total: number;
  summary: AdminCustomCompaniesSummary;
  /**
   * false when this database has no E7 tables (production today). Everything
   * else is zeroed/empty and the page renders its EmptyState — NOT an error.
   */
  schemaPresent: boolean;
}

/**
 * One attempt's terminal state. SEVEN of these are literal `outcome` column
 * values; `discovery_pending` is SPLIT server-side into two, because a
 * submission ten seconds old is legitimately in flight and calling it "stuck"
 * is a false alarm:
 *   - `pending` — newest row is discovery_pending and younger than the grace
 *   - `stuck`   — newest row is discovery_pending and older than the grace
 * Past that grace the reconcile sweeper SHOULD have refused the row and did
 * not — which is exactly the thing an admin wants to see.
 */
export type AttemptOutcome =
  | 'added'
  | 'already_public'
  | 'refused'
  | 'unsupported'
  | 'empty'
  | 'probe_failed'
  | 'pending'
  | 'stuck';

/**
 * One ADD ATTEMPT — not one audit row.
 *
 * A single submission of a non-ATS URL writes TWO `company_add_attempts` rows
 * (an interim `discovery_pending` from the request path, then a terminal one
 * from the worker). The backend collapses them to the newest row and carries
 * the span metadata (`firstSeenAt` / `auditRowCount` / `decidedInS`) forward
 * from the rows it swallowed.
 */
export interface AdminCustomCompanyAttemptRow {
  /** `company_add_attempts.id` of the TERMINAL (newest) row of this attempt. */
  id: number;
  /**
   * Stable React key. `company_id` when set, else `attempt#<id>` — NOT just
   * company_id, because the column is nullable (unsupported / empty /
   * probe_failed write none) and every NULL would collapse into one row.
   */
  attemptKey: string;

  /** ISO — the terminal row. */
  createdAt: string;
  /** ISO — the earliest audit row for this attempt. */
  firstSeenAt: string;
  /** How many `company_add_attempts` rows collapsed into this one. */
  auditRowCount: number;
  /**
   * Seconds from the immediately-preceding `discovery_pending` row to the
   * terminal row. null when the previous row was not a pending (an idempotent
   * re-add, or a single-row ATS attempt).
   */
  decidedInS: number | null;

  /** Soft link — there is deliberately NO foreign key, so the audit survives. */
  userId: string;
  /** LEFT JOIN users; null when the user row is gone. Fall back to `userId`. */
  userEmail: string | null;
  userDisplayName: string | null;

  submittedUrl: string;
  normalizedUrl: string | null;
  /** 'discovered' | 'workday' | 'script' | … | null. */
  resolvedAts: string | null;
  boardToken: string | null;

  /** The DERIVED outcome (pending / stuck instead of discovery_pending). */
  outcome: AttemptOutcome;
  /** The literal column value, kept for diagnosis. */
  rawOutcome: string;
  /** Verbatim, stored as "<step>: <reason>". */
  errorDetail: string | null;
  /** Text before the FIRST ": " in errorDetail. null when errorDetail is null. */
  failedStep: string | null;
  /** Everything after the first ": ". Falls back to the whole string. */
  failureReason: string | null;

  companyId: string | null;
  /** false = the `companies` row was HARD-DELETED. The UI degrades to the URL. */
  companyExists: boolean;
  companyDisplayName: string | null;
  /** 'user' | 'public' — `already_public` points at a public id. */
  companyVisibility: string | null;
  companyHealthState: string | null;
  /** null when companyExists is false or visibility <> 'user'. */
  companyLiveStatus: CustomCompanyLiveStatus | null;
  /**
   * `provider_config->'discovery'->'steps'` — the 5-rung checklist, or null
   * once the company row is gone (the expansion then falls back to
   * `errorDetail` alone). NEVER carries `->'network'`: that blob is the full
   * request log plus a payload sample and would ride every page.
   */
  discoverySteps: DiscoveryStep[] | null;
}

/** One row of the per-user rollup (Table 3). Always unfiltered. */
export interface AdminCustomCompanyUserRow {
  userId: string;
  email: string | null;
  displayName: string | null;
  attempts: number;
  added: number;
  refused: number;
  stuck: number;
  pending: number;
  /** `already_public` — the table's "Linked" column. */
  alreadyPublic: number;
  /** unsupported + empty + probe_failed. */
  otherFailed: number;
  /** Custom companies they own RIGHT NOW. != added, because deletes hard-delete. */
  ownsNow: number;
  /** ISO — over ALL audit rows, so this is the real first submit. */
  firstAttemptAt: string;
  lastAttemptAt: string;
}

export interface AdminCustomCompanyAttemptsResponse {
  attempts: AdminCustomCompanyAttemptRow[];
  /** Attempts matching the filters, BEFORE limit/offset. Drives the pager. */
  total: number;
  /** ALWAYS over ALL attempts, ignoring filters. Drives the Table-2 subtitle. */
  byOutcome: Partial<Record<AttemptOutcome, number>>;
  /** ALWAYS over ALL attempts, ignoring filters. Also feeds the User dropdown. */
  users: AdminCustomCompanyUserRow[];
  /** true when the rollup hit its server-side cap. */
  usersTruncated: boolean;
  schemaPresent: boolean;
}

/** One page request for the custom-companies list (server-side pagination). */
export interface AdminCustomCompaniesArgs {
  page: number;
  rowsPerPage: number;
  health?: string;
  search?: string;
}

/** One page request for the add-attempts list (server-side pagination). */
export interface AdminCustomCompanyAttemptsArgs {
  page: number;
  rowsPerPage: number;
  outcome?: AttemptOutcome;
  userId?: string;
  search?: string;
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
  /**
   * Subcategory coverage. `sweSubcategorized` counts EVALUATED rows
   * (`IS NOT NULL`), not non-empty ones — `[]` is a legitimate terminal answer,
   * and the non-empty definition can never cross the 90% reveal threshold.
   * `subcategoryUnknownSlugs` is the compensating control for the array having
   * no FK and MUST be permanently 0 — including through Phase 1, where the
   * backend compares against the code taxonomy because the dimension table is
   * still empty.
   *
   * All four are OPTIONAL-BY-DEFAULT at runtime: a backend that predates them
   * omits them and the transform coerces to 0 rather than throwing. See the
   * comment on the health guard for why that exception exists.
   */
  sweOpenTotal: number;
  sweSubcategorized: number;
  sweSubcategoryLabelled: number;
  subcategoryUnknownSlugs: number;
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
  /**
   * ORDERED SWE subcategory slugs (index 0 = primary), tri-state:
   * `null` = never evaluated, `[]` = evaluated and nothing applies.
   * NEVER coerce to `[]` — the two states drive different UI.
   */
  subcategories: string[] | null;
  subcategoryConfidence: number | null;
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
  /**
   * ORDERED SWE subcategory slugs (index 0 = primary), tri-state:
   * `null` = never evaluated, `[]` = evaluated and nothing applies.
   * NEVER coerce to `[]` — the two states drive different UI.
   */
  subcategories: string[] | null;
  subcategoryConfidence: number | null;
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
  /** One of enriched_at | classify_confidence | judge_confidence | subcategory_confidence. */
  sort?: string;
  sortDir?: 'asc' | 'desc';
  subcategory?: string;
  /** any | unlabelled_swe | labelled. */
  subcategoryState?: string;
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
  /**
   * ORDERED SWE subcategory slugs (index 0 = primary), tri-state:
   * `null` = never evaluated, `[]` = evaluated and nothing applies.
   * NEVER coerce to `[]` — the two states drive different UI.
   */
  subcategories: string[] | null;
  subcategoryConfidence: number | null;
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
  /**
   * OPTIONAL, and the optionality is the whole contract. OMITTING the key means
   * "leave the stored array alone" — which is what stops a level-only
   * correction from wiping a backfilled label and then locking the row. `null`
   * means "re-queue this row". Never send `subcategories: undefined` expecting
   * it to be dropped by chance; build the body without the key.
   */
  subcategories?: string[] | null;
  tags: string[];
  note?: string | null;
}

/** Correction / re-enrich response. */
/** One runtime-tunable setting row. `updatedAt` is null for a materialized default. */
export interface AdminSettingRow {
  key: string;
  value: unknown;
  updatedAt: string | null;
  updatedBy: string | null;
}

export interface EnrichmentCorrectionResult {
  sourceId: string;
  jobListingId: string;
  enrichmentStatus: string | null;
  category: string | null;
  level: string | null;
  /** Read BACK from the row, so the not-sent path reports what is stored. */
  subcategories: string[] | null;
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
    'AdminCustomCompanies',
    'AdminCustomCompanyAttempts',

    'AdminSettings',
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
        // ⚠ THE COVERAGE COUNTERS ARE A DELIBERATE EXCEPTION TO THE THROWING
        // GUARD ABOVE. They are NOT in the throw list, and they must not be: a
        // backend that predates them omits all four, and a throwing check would
        // blank the ENTIRE admin SPA during the deploy window between the
        // frontend shipping and Railway catching up. A missing counter renders
        // as 0, which is both harmless and true (nothing has been evaluated
        // yet). The banner-critical fields above keep their hard guard because
        // a wrong verdict is worse than no page.
        const num = (v: unknown): number => (typeof v === 'number' ? v : 0);
        return {
          ...(res as unknown as EnrichmentHealth),
          sweOpenTotal: num(res.sweOpenTotal),
          sweSubcategorized: num(res.sweSubcategorized),
          sweSubcategoryLabelled: num(res.sweSubcategoryLabelled),
          subcategoryUnknownSlugs: num(res.subcategoryUnknownSlugs),
        };
      },
      providesTags: ['EnrichmentHealth'],
    }),

    listEnrichmentNeedsHuman: builder.query<EnrichmentNeedsHumanResponse, EnrichmentNeedsHumanArgs>(
      {
        query: ({
          limit,
          offset,
          company,
          category,
          level,
          includeCorrected,
          onlyOpen,
          sort,
          sortDir,
          subcategory,
          subcategoryState,
        }) => ({
          url: '/enrichment/needs-human',
          params: {
            limit,
            offset,
            ...(company ? { company } : {}),
            ...(category ? { category } : {}),
            ...(level ? { level } : {}),
            ...(includeCorrected ? { includeCorrected } : {}),
            ...(onlyOpen === false ? { onlyOpen } : {}),
            ...(sort ? { sort } : {}),
            ...(sortDir ? { sortDir } : {}),
            ...(subcategory ? { subcategory } : {}),
            ...(subcategoryState && subcategoryState !== 'any'
              ? { subcategoryState }
              : {}),
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
            for (const field of [
              'classifyConfidence',
              'judgeConfidence',
              'subcategoryConfidence',
            ] as const) {
              const val = row[field];
              if (val !== null && val !== undefined && typeof val !== 'number') {
                throw new Error(
                  `Invalid /api/admin/enrichment/needs-human response: ${field} must be number or null`
                );
              }
            }
            // ⚠ SEPARATE Array.isArray GUARD, deliberately NOT folded into the
            // `string | null` loop below — a CORRECT array value would throw
            // there. `null` is legal (never evaluated) and so is `[]`.
            if (
              row.subcategories !== null &&
              row.subcategories !== undefined &&
              !Array.isArray(row.subcategories)
            ) {
              throw new Error(
                'Invalid /api/admin/enrichment/needs-human response: subcategories must be an array or null'
              );
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
          for (const field of [
            'classifyConfidence',
            'judgeConfidence',
            'subcategoryConfidence',
          ] as const) {
            const val = row[field];
            if (val !== null && val !== undefined && typeof val !== 'number') {
              throw new Error(
                `Invalid /api/admin/enrichment/recent response: ${field} must be number or null`
              );
            }
          }
          // ⚠ SEPARATE Array.isArray guard — see the identical note on the
          // needs-human transform. Putting `subcategories` in the string|null
          // loop below would throw on a correct value.
          if (
            row.subcategories !== null &&
            row.subcategories !== undefined &&
            !Array.isArray(row.subcategories)
          ) {
            throw new Error(
              'Invalid /api/admin/enrichment/recent response: subcategories must be an array or null'
            );
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

    // Runtime settings. The backend materializes a default row for every
    // allowlisted key, so this never returns a partial list and the UI never
    // has to render "missing".
    getAdminSettings: builder.query<AdminSettingRow[], void>({
      query: () => ({ url: '/settings' }),
      transformResponse: (res: unknown): AdminSettingRow[] => {
        if (!isRecord(res) || !Array.isArray(res.settings)) {
          throw new Error('Invalid /api/admin/settings response');
        }
        for (const row of res.settings) {
          if (!isRecord(row) || typeof row.key !== 'string') {
            throw new Error('Invalid /api/admin/settings response: malformed row');
          }
          // `updatedAt` renders through `new Date(...)`; an object would be an
          // Invalid-Date crash and the only ErrorBoundary is app-root.
          if (
            row.updatedAt !== null &&
            row.updatedAt !== undefined &&
            typeof row.updatedAt !== 'string'
          ) {
            throw new Error(
              'Invalid /api/admin/settings response: updatedAt must be string or null'
            );
          }
        }
        return res.settings as unknown as AdminSettingRow[];
      },
      providesTags: ['AdminSettings'],
    }),

    updateAdminSetting: builder.mutation<AdminSettingRow, { key: string; value: unknown }>({
      query: ({ key, value }) => ({
        url: `/settings/${encodeURIComponent(key)}`,
        method: 'PUT',
        body: { value },
      }),
      invalidatesTags: ['AdminSettings'],
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

    // ─────────────────────────────────────────────────────────────────────────
    // Custom Companies (E7) oversight — two read-only GETs behind AdminRoute.
    // ─────────────────────────────────────────────────────────────────────────

    getAdminCustomCompanies: builder.query<AdminCustomCompaniesResponse, AdminCustomCompaniesArgs>({
      query: ({ page, rowsPerPage, health, search }) => ({
        url: '/custom-companies',
        params: {
          limit: rowsPerPage,
          offset: page * rowsPerPage,
          ...(health ? { health } : {}),
          ...(search ? { search } : {}),
        },
      }),
      transformResponse: (res: unknown): AdminCustomCompaniesResponse => {
        // Runtime guard — same reasoning as listAdminFeedback: a 2xx body with
        // the wrong shape (CDN error page, serializer regression) would
        // otherwise render an empty table and four zeroed StatTiles with no
        // error signal at all, which is the exact failure this page exists to
        // catch elsewhere.
        if (
          !isRecord(res) ||
          !Array.isArray(res.companies) ||
          typeof res.total !== 'number' ||
          !isRecord(res.summary) ||
          typeof res.summary.trackedCount !== 'number'
        ) {
          throw new Error('Invalid /api/admin/custom-companies response');
        }
        for (const row of res.companies) {
          // ``id`` is the React key and ``liveStatus`` keys the chip map; a
          // missing/renamed one is a blank chip or a duplicate-key warning
          // rather than a visible failure.
          if (!isRecord(row) || typeof row.id !== 'string' || typeof row.liveStatus !== 'string') {
            throw new Error('Invalid /api/admin/custom-companies response: malformed row');
          }
        }
        return res as unknown as AdminCustomCompaniesResponse;
      },
      providesTags: ['AdminCustomCompanies'],
    }),

    getAdminCustomCompanyAttempts: builder.query<
      AdminCustomCompanyAttemptsResponse,
      AdminCustomCompanyAttemptsArgs
    >({
      query: ({ page, rowsPerPage, outcome, userId, search }) => ({
        url: '/custom-companies/attempts',
        params: {
          limit: rowsPerPage,
          offset: page * rowsPerPage,
          ...(outcome ? { outcome } : {}),
          // snake_case on purpose — it is the backend's Query parameter name,
          // and the Vercel proxy forwards query params verbatim.
          ...(userId ? { user_id: userId } : {}),
          ...(search ? { search } : {}),
        },
      }),
      transformResponse: (res: unknown): AdminCustomCompanyAttemptsResponse => {
        if (
          !isRecord(res) ||
          !Array.isArray(res.attempts) ||
          typeof res.total !== 'number' ||
          !isRecord(res.byOutcome) ||
          !Array.isArray(res.users)
        ) {
          throw new Error('Invalid /api/admin/custom-companies/attempts response');
        }
        for (const row of res.attempts) {
          if (
            !isRecord(row) ||
            typeof row.attemptKey !== 'string' ||
            typeof row.outcome !== 'string' ||
            typeof row.submittedUrl !== 'string'
          ) {
            throw new Error(
              'Invalid /api/admin/custom-companies/attempts response: malformed attempt'
            );
          }
          // ``discoverySteps`` is null for the common case (the company row was
          // hard-deleted) and an array otherwise. Anything else reaches a
          // ``.map()`` in the expansion and crashes the render — and the only
          // ErrorBoundary is app-root, so that blanks the whole SPA.
          if (row.discoverySteps != null && !Array.isArray(row.discoverySteps)) {
            throw new Error(
              'Invalid /api/admin/custom-companies/attempts response: discoverySteps must be an array or null'
            );
          }
        }
        for (const user of res.users) {
          if (!isRecord(user) || typeof user.userId !== 'string') {
            throw new Error(
              'Invalid /api/admin/custom-companies/attempts response: malformed user rollup row'
            );
          }
        }
        return res as unknown as AdminCustomCompanyAttemptsResponse;
      },
      providesTags: ['AdminCustomCompanyAttempts'],
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
  useGetAdminCustomCompaniesQuery,
  useGetAdminCustomCompanyAttemptsQuery,

  useGetAdminSettingsQuery,
  useUpdateAdminSettingMutation,
} = adminApi;
