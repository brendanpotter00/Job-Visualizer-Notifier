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
  tagTypes: ['AdminUsers', 'AdminUsersStats', 'AdminFeedback'],
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
  }),
});

export const {
  useListAdminFeedbackQuery,
  useListAdminUsersQuery,
  useGetAdminUsersStatsQuery,
  useGrantAdminMutation,
  useRevokeAdminMutation,
} = adminApi;
