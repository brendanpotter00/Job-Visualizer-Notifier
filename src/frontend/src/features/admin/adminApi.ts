import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

export type SignupProvider = 'google' | 'email' | 'other';

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
  tagTypes: ['AdminUsers', 'AdminUsersStats'],
  endpoints: (builder) => ({
    listAdminUsers: builder.query<AdminUserRow[], void>({
      query: () => '/users',
      transformResponse: (res: AdminUsersListResponse) => {
        // Runtime guard: catches the "proxy returns 2xx with the wrong
        // body" case (e.g. CDN error page misrouted, future server
        // wraps the envelope for pagination). Without this, the consumer
        // gets ``undefined`` and silently renders an empty roster — the
        // exact "silently zero admins" failure mode this PR exists to
        // prevent.
        if (!res || !Array.isArray(res.users)) {
          throw new Error(
            'Invalid /api/admin/users response: missing users[]'
          );
        }
        return res.users;
      },
      providesTags: ['AdminUsers'],
    }),
    getAdminUsersStats: builder.query<AdminUsersStats, void>({
      query: () => '/users/stats',
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
  useListAdminUsersQuery,
  useGetAdminUsersStatsQuery,
  useGrantAdminMutation,
  useRevokeAdminMutation,
} = adminApi;
