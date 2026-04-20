import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

export interface FeatureListItem {
  id: string;
  title: string;
  description: string;
  createdAt: string;
  upvoteCount: number;
  hasUpvoted: boolean;
}

export interface UpvoteMutationResult {
  featureId: string;
  upvoteCount: number;
  hasUpvoted: boolean;
}

interface FeaturesApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}

export const featuresApi = createApi({
  reducerPath: 'featuresApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/features',
    prepareHeaders: async (headers, { extra }) => {
      const { getTokenOrNull } = extra as FeaturesApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  tagTypes: ['Features'],
  endpoints: (builder) => ({
    listFeatures: builder.query<FeatureListItem[], void>({
      query: () => '',
      transformResponse: (res: { features: FeatureListItem[] }) => res.features,
      providesTags: ['Features'],
    }),
    upvoteFeature: builder.mutation<UpvoteMutationResult, string>({
      query: (featureId) => ({ url: `${featureId}/upvote`, method: 'POST' }),
      async onQueryStarted(featureId, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          featuresApi.util.updateQueryData('listFeatures', undefined, (draft) => {
            const f = draft.find((x) => x.id === featureId);
            if (f && !f.hasUpvoted) {
              f.hasUpvoted = true;
              f.upvoteCount += 1;
            }
          })
        );
        try {
          await queryFulfilled;
        } catch (err) {
          // Log BEFORE undo so the rejection reason is observable; downstream
          // consumers (e.g. FeatureVoteCard) also log via `.unwrap().catch`,
          // but the mutation layer is the only place that sees the raw
          // rejection before the cache is reverted.
          console.warn(
            `[featuresApi] upvote failed for feature=${featureId}, reverting:`,
            err
          );
          patch.undo();
        }
      },
    }),
    removeUpvote: builder.mutation<UpvoteMutationResult, string>({
      query: (featureId) => ({ url: `${featureId}/upvote`, method: 'DELETE' }),
      async onQueryStarted(featureId, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          featuresApi.util.updateQueryData('listFeatures', undefined, (draft) => {
            const f = draft.find((x) => x.id === featureId);
            if (f && f.hasUpvoted) {
              f.hasUpvoted = false;
              f.upvoteCount = Math.max(0, f.upvoteCount - 1);
            }
          })
        );
        try {
          await queryFulfilled;
        } catch (err) {
          console.warn(
            `[featuresApi] remove-upvote failed for feature=${featureId}, reverting:`,
            err
          );
          patch.undo();
        }
      },
    }),
  }),
});

export const {
  useListFeaturesQuery,
  useUpvoteFeatureMutation,
  useRemoveUpvoteMutation,
} = featuresApi;
