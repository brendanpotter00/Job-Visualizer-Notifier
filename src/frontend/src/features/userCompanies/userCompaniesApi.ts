import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Job } from '../../types';
import type { BackendJobListing } from '../../api/types';
import { transformBackendJob } from '../../api/transformers/backendScraperTransformer';

/**
 * ATS providers `POST /api/companies/resolve` can currently name.
 *
 * The backend types this field as a bare `str`, so a newer server could return
 * a provider this build has never heard of. Display code must therefore treat
 * an unknown value as data, not as an impossible state — see `atsLabel()`.
 */
export type AtsProvider = 'greenhouse' | 'ashby' | 'lever' | 'gem' | 'workday' | 'eightfold';

/** How the resolver arrived at the candidate board. Also a bare `str` on the wire. */
export type ResolveVia = 'direct' | 'redirect' | 'embedded';

/** A job board the resolver recognized behind the pasted URL. */
export interface AtsCandidate {
  ats: AtsProvider;
  boardToken: string;
  /** Provider-specific extras (e.g. Workday's `baseUrl` / `tenantSlug`). Often empty. */
  providerConfig: Record<string, string>;
  /** The URL the candidate was actually discovered on (may differ from what was pasted). */
  sourceUrl: string;
}

/** What the real ATS client saw when it called the candidate board. */
export interface ProbeResult {
  /** False means the board was identified but calling it failed — see `error`. */
  ok: boolean;
  jobCount: number;
  error: string | null;
}

/** 200 body. Persists nothing — this endpoint is a read-only preview. */
export interface ResolveUrlResponse {
  candidate: AtsCandidate;
  probe: ProbeResult;
  via: ResolveVia;
  /** Redirect chain that was followed, oldest first. Empty for a direct hit. */
  hops: string[];
  finalUrl: string;
}

/**
 * The 422 body for a *resolver* failure.
 *
 * Deliberately FLAT (`reason` / `finalUrl` / `hops`), not nested under
 * `detail`. FastAPI's own request-validation 422 is a different shape
 * (`{ detail: [...] }`) with no `reason` key at all — `resolveErrors.ts` is
 * responsible for telling the two apart.
 *
 * `reason` is typed as `string` rather than a closed union because the server
 * owns the code list and can add to it; the mapper narrows it and falls back
 * to generic copy (while still surfacing the raw code) for anything unknown.
 */
export interface ResolveUrlFailure {
  reason: string;
  finalUrl: string;
  hops: string[];
}

export interface ResolveUrlArgs {
  url: string;
}

/**
 * Health lifecycle a stored user-company can be in. The wire value is a bare
 * `str` (backend-owned, may add codes), so display code narrows it and falls
 * back to raw text — see `companyHealth.ts`.
 *
 * `'discovering'` is the PROVISIONAL state a non-ATS board sits in between the
 * `202` add and the one-time capture discovery finishing (E7 capture
 * pivot): the row exists (so the list shows it as "Setting up…") but nothing is
 * scraped yet. The discovery task flips it to `'unverified'` (tracked) or
 * `'refused'`.
 */
export type UserCompanyHealthState =
  | 'discovering'
  | 'unverified'
  | 'healthy'
  | 'quarantined'
  | 'refused';

/**
 * The four steps a one-time discovery walks, in display order (E7 capture pivot).
 *
 * A CLOSED union on purpose, unlike `healthState`: the backend owns the vocabulary
 * (`api/services/discovery/progress.py`) and normalizes unknown keys away before they
 * reach the wire, so a rename there should be a compile error here — not a blank rung
 * in a checklist the user is reading to decide what to do next.
 */
export type DiscoveryStepKey = 'open_page' | 'find_feed' | 'verify_read' | 'ready';

/** Per-step state. `failed` lands on at most one step per run. */
export type DiscoveryStepStatus = 'pending' | 'active' | 'done' | 'failed';

/** Terminal-ness of the whole run. `running` includes "queued but not started". */
export type DiscoveryOutcomeState = 'running' | 'tracking' | 'refused';

export interface DiscoveryStep {
  key: DiscoveryStepKey;
  status: DiscoveryStepStatus;
  /**
   * The SPECIFIC thing this step found ("found 3 candidate feeds", "read 90 jobs"), or
   * — on the failed step — why it stopped. Null while pending. A generic tick would be
   * a spinner with extra steps, which is what this replaced.
   */
  result: string | null;
}

/** One job from the acceptance replay. `url` is present only when it's an http(s) link. */
export interface DiscoveryJobPreview {
  title: string;
  location?: string;
  url?: string;
}

/**
 * The discovery checklist attached to a user company, when it has one.
 *
 * Rides the SAME `GET /api/users/companies` payload the list already polls — there is
 * deliberately no second polling channel. Absent (`undefined`) for every ATS company
 * and for anything discovered before this shipped.
 */
export interface DiscoveryProgress {
  /** Always all four steps, in order — the backend fills missing ones as `pending`. */
  steps: DiscoveryStep[];
  outcome: DiscoveryOutcomeState;
  /**
   * Hosted, iframe-embeddable view of the capture session. Only a Browserbase run has
   * one and our default is our own Chromium, so this is null on nearly every discovery
   * — the UI treats it as an optional extra and never blocks the checklist on it.
   */
  liveViewUrl: string | null;
  updatedAt: string | null;
  jobPreview: DiscoveryJobPreview[];
}

/**
 * A company the signed-in user brought themselves — one row of
 * `GET /api/users/companies`, and the body of a successful add. camelCase on
 * the wire (backend `to_camel`).
 */
export interface UserCompany {
  /** `u-<10 base36>` runtime id. NOT a compile-time `COMPANY_IDS` member. */
  id: string;
  displayName: string;
  /** Bare `str` on the wire (see `AtsProvider` note above). */
  ats: string;
  boardToken: string;
  /** `custom:<id>` — per-company job namespace. */
  sourceId: string;
  /** See `UserCompanyHealthState`; typed wide because the server owns the list. */
  healthState: string;
  openJobCount: number;
  /** ISO-8601 of the last successful harvest, or null before the first run. */
  lastSuccessAt: string | null;
  /**
   * ISO-8601 of the first VERIFIED harvest (E7 Phase 2), or null until the
   * company graduates. The trend page uses it to shade the pre-tracking seed
   * bucket ("N openings already live when tracking began").
   */
  trackingStartedAt: string | null;
  /**
   * The 4-step discovery checklist. Optional because it exists only for a discovered
   * (non-ATS) board — and because a server that predates it simply omits the field.
   */
  discovery?: DiscoveryProgress | null;
}

/** `GET /api/users/companies` envelope — newest first. */
export interface GetUserCompaniesResponse {
  companies: UserCompany[];
}

/** Arg for the owner-scoped jobs + delete endpoints. */
export interface UserCompanyIdArg {
  id: string;
}

/**
 * The 422 body when an add is rejected. Distinct from the *resolver's* flat 422
 * (`ResolveUrlFailure`): the add failure carries a human `detail` and the
 * `finalUrl` that was probed. `reason` is one of
 * `unsupported | probe_failed | empty | deadline_exceeded | no_ats_detected`,
 * typed as `string` because the server owns the code list.
 */
export interface AddUserCompanyFailure {
  reason: string;
  detail: string;
  finalUrl: string;
}

/**
 * The `202 Accepted` body when a non-ATS URL is handed to one-time discovery
 * (E7 Phase 3b). The board isn't tracked yet — a background agent is teaching
 * itself to read it, and the company surfaces in the list after the first scan
 * (or as a `refused` health badge if it can't be tracked). Distinct from the
 * `UserCompany` success body by its `status` discriminant.
 */
export interface DiscoveryPendingResponse {
  status: 'discovery_pending';
  detail: string;
  finalUrl?: string;
  /**
   * The provisional row's runtime id (and its `custom:<id>` namespace). Without these
   * the caller could only find the board it just added by diffing the list, so the
   * "one-time setup" notice could never point at the row now narrating its own
   * progress. Optional — a server that predates the checklist omits them.
   */
  id?: string;
  sourceId?: string;
}

/**
 * `addUserCompany` resolves to a tracked `UserCompany` (201/200, ATS boards or an
 * idempotent re-add) OR a `DiscoveryPendingResponse` (202, a non-ATS URL routed to
 * one-time discovery). Consumers discriminate with {@link isDiscoveryPending}.
 */
export type AddUserCompanyResult = UserCompany | DiscoveryPendingResponse;

export function isDiscoveryPending(
  result: AddUserCompanyResult,
): result is DiscoveryPendingResponse {
  return (result as DiscoveryPendingResponse).status === 'discovery_pending';
}

interface UserCompaniesApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}

export const userCompaniesApi = createApi({
  reducerPath: 'userCompaniesApi',
  baseQuery: fetchBaseQuery({
    // `/api` and NOT `/api/companies` on purpose. This slice owns the whole
    // "companies the user brings themselves" surface, and the follow-up work
    // adds `users/companies` endpoints (list / add / remove) alongside the
    // `companies/resolve` probe below. Those live under a different path
    // prefix, so pinning the base to `/api/companies` here would force the
    // next endpoints to escape it with `../`.
    baseUrl: '/api',
    prepareHeaders: async (headers, { extra }) => {
      const { getTokenOrNull } = extra as UserCompaniesApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  // `resolve` still writes nothing, but the `users/companies` list below is
  // real server state, so the slice now owns one tag. Per-company job caches
  // tag `{ type: 'MyCompanies', id }`; the list tags the bare type, and add /
  // remove invalidate the bare type (which sweeps both the list and per-id
  // job caches). One tag type keeps the invalidation graph trivial for Phase 1.
  tagTypes: ['MyCompanies'],
  endpoints: (builder) => ({
    resolveCareersUrl: builder.mutation<ResolveUrlResponse, ResolveUrlArgs>({
      query: ({ url }) => ({
        url: 'companies/resolve',
        method: 'POST',
        body: { url },
      }),
    }),

    /** The caller's own companies, newest first. */
    getUserCompanies: builder.query<UserCompany[], void>({
      query: () => 'users/companies',
      // Unwrap the `{ companies: [...] }` envelope to the array components consume.
      transformResponse: (response: GetUserCompaniesResponse) => response.companies,
      providesTags: ['MyCompanies'],
    }),

    /**
     * Add a company from an already-resolved final URL. On `201` (created) or
     * an idempotent `200` (already owned) the body is the `UserCompany`; on `202`
     * a non-ATS URL was routed to one-time discovery and the body is a
     * `DiscoveryPendingResponse` (discriminate with `isDiscoveryPending`); a `422`
     * surfaces `AddUserCompanyFailure` in `error.data` for the UI to explain.
     */
    addUserCompany: builder.mutation<AddUserCompanyResult, ResolveUrlArgs>({
      query: ({ url }) => ({
        url: 'users/companies',
        method: 'POST',
        body: { url },
      }),
      invalidatesTags: ['MyCompanies'],
    }),

    /** Drop the caller's ownership of a company (`204`; `404` if not owned). */
    removeUserCompany: builder.mutation<void, string>({
      query: (id) => ({
        url: `users/companies/${id}`,
        method: 'DELETE',
      }),
      invalidatesTags: ['MyCompanies'],
    }),

    /**
     * Owner-scoped jobs for one custom company (`403` if the caller is not an
     * owner). The response is the SAME shape `/api/jobs` returns, so it runs
     * through the exact transform the backend-scraper client uses
     * (`transformBackendJob`) — the mapping is never duplicated here. Emits the
     * frontend `Job[]` (camelCase, with `firstSeenAt`) the trend page needs.
     */
    getUserCompanyJobs: builder.query<Job[], UserCompanyIdArg>({
      query: ({ id }) => `users/companies/${id}/jobs`,
      transformResponse: (rows: BackendJobListing[], _meta, { id }) =>
        rows.map((row) => transformBackendJob(row, id)),
      providesTags: (_result, _error, { id }) => [{ type: 'MyCompanies', id }],
    }),
  }),
});

export const {
  useResolveCareersUrlMutation,
  useGetUserCompaniesQuery,
  useAddUserCompanyMutation,
  useRemoveUserCompanyMutation,
  useGetUserCompanyJobsQuery,
} = userCompaniesApi;
