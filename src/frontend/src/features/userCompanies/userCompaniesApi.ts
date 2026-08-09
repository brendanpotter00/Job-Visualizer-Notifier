import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

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
  // No `tagTypes` / `providesTags`: resolve writes nothing, so there is no
  // server state for this slice to invalidate yet.
  endpoints: (builder) => ({
    resolveCareersUrl: builder.mutation<ResolveUrlResponse, ResolveUrlArgs>({
      query: ({ url }) => ({
        url: 'companies/resolve',
        method: 'POST',
        body: { url },
      }),
    }),
  }),
});

export const { useResolveCareersUrlMutation } = userCompaniesApi;
