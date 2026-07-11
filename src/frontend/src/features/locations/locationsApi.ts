import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { serializeParamsWithEncodedSpaces } from '../savedFilters/savedFiltersApi.ts';

/**
 * One canonical location returned by the PUBLIC location-search endpoint
 * (`GET /api/locations/search`). Unlike the old saved-filters variant this
 * carries the structured `city`/`region`/`country`/`remoteScope` columns in
 * addition to the display `canonicalName`, so a selected option can be cached
 * as a full descriptor and resolved by the hierarchical job-location filter —
 * even for non-US countries / irregular regions the frontend can't re-derive
 * from the label string alone.
 */
export interface LocationSearchResult {
  id: number;
  canonicalName: string;
  kind: string;
  city: string | null;
  region: string | null;
  country: string | null;
  remoteScope: string | null;
}

/** Args for the debounced location autocomplete. */
export interface SearchLocationsArgs {
  q: string;
  limit?: number;
  /** Only return locations that currently have at least one OPEN job. */
  openOnly?: boolean;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return v != null && typeof v === 'object' && !Array.isArray(v);
}

function isNullableString(v: unknown): v is string | null {
  return v === null || typeof v === 'string';
}

/**
 * Validate an untrusted search response into `LocationSearchResult[]`. A 2xx
 * body of the wrong shape (CDN error page, serializer regression) must surface
 * as an error rather than silently feeding malformed descriptors into the
 * location filter's catalog. Exported for unit testing.
 */
export function validateLocationSearchResults(res: unknown): LocationSearchResult[] {
  if (!Array.isArray(res)) {
    throw new Error('Invalid /api/locations/search response: body is not an array');
  }
  for (const row of res) {
    if (
      !isRecord(row) ||
      typeof row.id !== 'number' ||
      typeof row.canonicalName !== 'string' ||
      typeof row.kind !== 'string' ||
      !isNullableString(row.city) ||
      !isNullableString(row.region) ||
      !isNullableString(row.country) ||
      !isNullableString(row.remoteScope)
    ) {
      throw new Error('Invalid /api/locations/search response: bad row shape');
    }
  }
  return res as LocationSearchResult[];
}

/**
 * Public canonical-location search. No auth header — the endpoint serves the
 * signed-out Recent Jobs and company hiring-trend pages (the Vercel proxy adds
 * the server-to-server internal key). Spaces are `%20`-encoded (not `+`) via
 * the shared serializer so multi-word queries like "New York" round-trip
 * through the proxy chain unambiguously.
 */
export const locationsApi = createApi({
  reducerPath: 'locationsApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/locations',
    paramsSerializer: serializeParamsWithEncodedSpaces,
  }),
  endpoints: (builder) => ({
    searchLocations: builder.query<LocationSearchResult[], SearchLocationsArgs>({
      query: ({ q, limit, openOnly }) => ({
        url: '/search',
        params: {
          q,
          ...(limit !== undefined ? { limit } : {}),
          ...(openOnly !== undefined ? { openOnly } : {}),
        },
      }),
      transformResponse: (res: unknown): LocationSearchResult[] =>
        validateLocationSearchResults(res),
    }),
  }),
});

export const { useSearchLocationsQuery } = locationsApi;
