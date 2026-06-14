import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';

/**
 * Max feedback length. Single-sourced here and mirrored by the backend
 * ``FeedbackSubmitRequest`` (``max_length=5000``) so the client-side guard and
 * the server validation agree.
 */
export const FEEDBACK_MAX_LENGTH = 5000;

export interface SubmitFeedbackArgs {
  message: string;
}

interface FeedbackApiExtra {
  getTokenOrNull: () => Promise<string | null>;
}

export const feedbackApi = createApi({
  reducerPath: 'feedbackApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/feedback',
    prepareHeaders: async (headers, { extra }) => {
      // Optional auth: anonymous submitters return null here, so no
      // Authorization header is sent and the backend stores a null user.
      const { getTokenOrNull } = extra as FeedbackApiExtra;
      const token = await getTokenOrNull();
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      return headers;
    },
  }),
  endpoints: (builder) => ({
    submitFeedback: builder.mutation<void, SubmitFeedbackArgs>({
      query: ({ message }) => ({
        url: '',
        method: 'POST',
        body: { message },
      }),
    }),
  }),
});

export const { useSubmitFeedbackMutation } = feedbackApi;
