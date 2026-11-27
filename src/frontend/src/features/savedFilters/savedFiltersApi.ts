import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import type { KeywordList, SearchTag, SavedFilters } from '../../types';

/** Body for creating a new keyword list. */
export interface CreateKeywordListArgs {
  name: string;
  tags: SearchTag[];
}

/** Body for patching an existing keyword list (all fields optional). */
export interface UpdateKeywordListArgs {
  id: string;
  name?: string;
  tags?: SearchTag[];
  position?: number;
}

/** The first-sign-in answers. Every list may be empty, which means "any". */
export interface OnboardingAnswers {
  category: string[];
  /** SWE specialties; the server keeps them only with `software_engineering` in `category`. */
  subcategory: string[];
  level: string[];
  /** Canonical location names (or the `United States` whole-country option). */
  locations: string[];
}

/** Body of `POST /api/users/onboarding`. */
export interface CompleteOnboardingArgs extends OnboardingAnswers {
  /** True for Skip (and any close of the questions). Skip keeps the answers. */
  skipped: boolean;
  /** The question on screen when the flow ended, 1-3 (analytics only). */
  step: 1 | 2 | 3;
  /** The PostHog session, when PostHog is on. */
  sessionId?: string;
}

/** Answer of `POST /api/users/onboarding`. */
export interface OnboardingResult {
  /** The account's stamp: this request's, or the earlier one on a repeat call. */
  onboardingCompletedAt: string;
  /** The account's saved filters after the call. */
  savedFilters: SavedFilters;
}

interface SavedFiltersApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}

/**
 * Serialize query params encoding spaces as `%20` rather than `+` (the
 * `URLSearchParams` default that RTK Query uses out of the box).
 *
 * The `/api/users/*` request chain (browser → Vercel rewrite → `api/users.ts`
 * proxy → FastAPI) does not reliably decode `+` back into a space, so a
 * multi-word location query like "San Fran" would otherwise reach the backend
 * `canonical_name ILIKE '%San+Fran%'` as a literal `+` and match nothing — even
 * though "San" alone matches San Francisco. `%20` round-trips unambiguously at
 * every hop. Only spaces are affected; numeric/boolean params are untouched.
 */
export function serializeParamsWithEncodedSpaces(params: Record<string, unknown>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) usp.set(key, String(value));
  }
  return usp.toString().replace(/\+/g, '%20');
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return v != null && typeof v === 'object' && !Array.isArray(v);
}

/**
 * Validate that an untrusted value is a `SearchTag[]`. A 2xx body with the
 * wrong shape (CDN error page, serializer regression) must surface as an error
 * rather than silently feeding malformed tags into the filter slices.
 */
function validateTags(value: unknown, ctx: string): SearchTag[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid ${ctx}: tags must be an array`);
  }
  for (const tag of value) {
    if (!isRecord(tag) || typeof tag.text !== 'string') {
      throw new Error(`Invalid ${ctx}: tag.text must be a string`);
    }
    if (tag.mode !== 'include' && tag.mode !== 'exclude') {
      throw new Error(`Invalid ${ctx}: tag.mode must be include|exclude`);
    }
  }
  return value as SearchTag[];
}

function validateKeywordList(value: unknown, ctx: string): KeywordList {
  if (!isRecord(value)) {
    throw new Error(`Invalid ${ctx}: keyword list is not an object`);
  }
  if (typeof value.id !== 'string') {
    throw new Error(`Invalid ${ctx}: list.id must be a string`);
  }
  if (typeof value.name !== 'string') {
    throw new Error(`Invalid ${ctx}: list.name must be a string`);
  }
  if (typeof value.isBuiltin !== 'boolean') {
    throw new Error(`Invalid ${ctx}: list.isBuiltin must be a boolean`);
  }
  if (typeof value.position !== 'number') {
    throw new Error(`Invalid ${ctx}: list.position must be a number`);
  }
  const tags = validateTags(value.tags, ctx);
  return {
    id: value.id,
    name: value.name,
    isBuiltin: value.isBuiltin,
    position: value.position,
    tags,
  };
}

/**
 * Exported for tests only — the same reason `serializeParamsWithEncodedSpaces`
 * is. Driving it through the endpoint would mean standing up
 * `fetchBaseQuery`'s absolute-URL machinery in jsdom, and the rejection cases
 * would then all pass on the wrong error.
 */
export function validateSavedFilters(res: unknown): SavedFilters {
  if (!isRecord(res)) {
    throw new Error('Invalid /api/users/saved-filters response: body is not an object');
  }
  if (typeof res.recentTimeWindow !== 'string') {
    throw new Error('Invalid /api/users/saved-filters response: recentTimeWindow must be a string');
  }
  if (typeof res.trendTimeWindow !== 'string') {
    throw new Error('Invalid /api/users/saved-filters response: trendTimeWindow must be a string');
  }
  if (!Array.isArray(res.locations) || res.locations.some((l) => typeof l !== 'string')) {
    throw new Error('Invalid /api/users/saved-filters response: locations must be a string array');
  }
  if (!Array.isArray(res.category) || res.category.some((c) => typeof c !== 'string')) {
    throw new Error('Invalid /api/users/saved-filters response: category must be a string array');
  }
  if (!Array.isArray(res.level) || res.level.some((l) => typeof l !== 'string')) {
    throw new Error('Invalid /api/users/saved-filters response: level must be a string array');
  }
  // TOLERANT on purpose, unlike its neighbours. EVERY stored saved-filters row
  // predates this feature and has no `subcategory` key, so a strict check
  // mirroring the two above would throw for every existing user and take down
  // ALL of their saved filters — time windows, locations, keyword lists — not
  // just the new field. Absent is legal; present-and-wrong is not.
  if (
    res.subcategory !== undefined &&
    (!Array.isArray(res.subcategory) || res.subcategory.some((s) => typeof s !== 'string'))
  ) {
    throw new Error('Invalid /api/users/saved-filters response: subcategory must be a string array');
  }
  // TOLERANT too, and NOT normalized on the way out (unlike `subcategory`):
  // absence IS the signal. An older backend does not send the key, and it 422s
  // a PUT that carries it (`extra='forbid'`), so writers send `companyCategory`
  // only when this GET returned it. Present-and-wrong is still an error.
  if (
    res.companyCategory !== undefined &&
    (!Array.isArray(res.companyCategory) ||
      res.companyCategory.some((s) => typeof s !== 'string'))
  ) {
    throw new Error(
      'Invalid /api/users/saved-filters response: companyCategory must be a string array'
    );
  }
  if (res.recentActiveKeywordListId !== null && typeof res.recentActiveKeywordListId !== 'string') {
    throw new Error(
      'Invalid /api/users/saved-filters response: recentActiveKeywordListId must be string or null'
    );
  }
  if (res.trendActiveKeywordListId !== null && typeof res.trendActiveKeywordListId !== 'string') {
    throw new Error(
      'Invalid /api/users/saved-filters response: trendActiveKeywordListId must be string or null'
    );
  }
  // NORMALIZE on the way out. Tolerating the missing key is only half the fix:
  // `SavedFilters.subcategory` is REQUIRED, and `draftFromServer` spreads it
  // (`[...p.subcategory]`), so returning `res` untouched would leave the field
  // undefined and throw a TypeError on the Saved Filters page instead. Legacy
  // rows come out as `[]`, which every consumer already reads as "no filter".
  return {
    ...(res as unknown as SavedFilters),
    subcategory: Array.isArray(res.subcategory) ? (res.subcategory as string[]) : [],
  };
}

/**
 * Validate the `POST /api/users/onboarding` answer. Its `savedFilters` goes
 * straight into the saved-filters cache and the live filter slices, so it gets
 * the same check as a `GET /api/users/saved-filters` body. Exported for tests.
 */
export function validateOnboardingResult(res: unknown): OnboardingResult {
  if (!isRecord(res)) {
    throw new Error('Invalid /api/users/onboarding response: body is not an object');
  }
  if (typeof res.onboardingCompletedAt !== 'string' || res.onboardingCompletedAt.length === 0) {
    throw new Error('Invalid /api/users/onboarding response: onboardingCompletedAt must be a string');
  }
  return {
    onboardingCompletedAt: res.onboardingCompletedAt,
    savedFilters: validateSavedFilters(res.savedFilters),
  };
}

export const savedFiltersApi = createApi({
  reducerPath: 'savedFiltersApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/users',
    paramsSerializer: serializeParamsWithEncodedSpaces,
    prepareHeaders: async (headers, { extra }) => {
      const { getTokenOrNull } = extra as SavedFiltersApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  tagTypes: ['SavedFilters', 'KeywordLists'],
  endpoints: (builder) => ({
    getSavedFilters: builder.query<SavedFilters, void>({
      query: () => '/saved-filters',
      transformResponse: (res: unknown) => validateSavedFilters(res),
      providesTags: ['SavedFilters'],
      // Keep the cache warm for 5 min so navigating back to Saved Filters (or
      // re-reading on another page) is instant rather than re-paying the
      // (cold-start-dominated) round trip. Mutations still invalidate.
      keepUnusedDataFor: 300,
    }),
    updateSavedFilters: builder.mutation<SavedFilters, SavedFilters>({
      query: (body) => ({ url: '/saved-filters', method: 'PUT', body }),
      transformResponse: (res: unknown) => validateSavedFilters(res),
      invalidatesTags: ['SavedFilters'],
    }),
    // Saves the first-sign-in answers and stamps the account. No
    // `invalidatesTags`: the answer carries the new saved filters, and the
    // caller writes them into the `getSavedFilters` cache itself
    // (`upsertQueryData`) together with the live filter slices, so a refetch
    // would only repeat what it already has.
    completeOnboarding: builder.mutation<OnboardingResult, CompleteOnboardingArgs>({
      query: (body) => ({ url: '/onboarding', method: 'POST', body }),
      transformResponse: (res: unknown) => validateOnboardingResult(res),
    }),
    getKeywordLists: builder.query<KeywordList[], void>({
      query: () => '/saved-filters/keyword-lists',
      transformResponse: (res: unknown): KeywordList[] => {
        if (!isRecord(res) || !Array.isArray(res.lists)) {
          throw new Error(
            'Invalid /api/users/saved-filters/keyword-lists response: missing lists[]'
          );
        }
        return res.lists.map((l) =>
          validateKeywordList(l, '/api/users/saved-filters/keyword-lists response')
        );
      },
      providesTags: ['KeywordLists'],
      keepUnusedDataFor: 300,
    }),
    createKeywordList: builder.mutation<KeywordList, CreateKeywordListArgs>({
      query: (body) => ({ url: '/saved-filters/keyword-lists', method: 'POST', body }),
      transformResponse: (res: unknown) =>
        validateKeywordList(res, 'POST /api/users/saved-filters/keyword-lists response'),
      invalidatesTags: ['KeywordLists'],
    }),
    updateKeywordList: builder.mutation<KeywordList, UpdateKeywordListArgs>({
      query: ({ id, ...patch }) => ({
        url: `/saved-filters/keyword-lists/${id}`,
        method: 'PATCH',
        body: patch,
      }),
      transformResponse: (res: unknown) =>
        validateKeywordList(res, 'PATCH /api/users/saved-filters/keyword-lists response'),
      invalidatesTags: ['KeywordLists'],
    }),
    deleteKeywordList: builder.mutation<void, string>({
      query: (id) => ({
        url: `/saved-filters/keyword-lists/${id}`,
        method: 'DELETE',
      }),
      // The backend NULLs any active-list pointer to this list in the same delete
      // transaction (saved_filters_service.delete_keyword_list), so refresh the
      // scalar saved filters too — otherwise the cached pointer stays stale and
      // the "Save active list" button reads spuriously dirty.
      invalidatesTags: ['KeywordLists', 'SavedFilters'],
    }),
  }),
});

export const {
  useGetSavedFiltersQuery,
  useUpdateSavedFiltersMutation,
  useCompleteOnboardingMutation,
  useGetKeywordListsQuery,
  useCreateKeywordListMutation,
  useUpdateKeywordListMutation,
  useDeleteKeywordListMutation,
} = savedFiltersApi;
