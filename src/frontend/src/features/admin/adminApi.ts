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
  byProvider: Record<string, number>;
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
      transformResponse: (res: { users: AdminUserRow[] }) => res.users,
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
