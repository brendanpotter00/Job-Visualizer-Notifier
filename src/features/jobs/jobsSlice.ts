import { createSlice } from '@reduxjs/toolkit';
import type { Job } from '../../types';
import { loadJobsForCompany } from './jobsThunks';

/**
 * Jobs state (normalized by company)
 */
export interface JobsState {
  byCompany: {
    [companyId: string]: {
      /** Job data */
      items: Job[];

      /** Last fetch timestamp */
      lastFetchedAt?: string;

      /** Loading state */
      isLoading: boolean;

      /** Error message if fetch failed */
      error?: string;

      /** Fetch metadata */
      metadata: {
        totalCount: number;
        softwareCount: number;
        oldestJobDate?: string;
        newestJobDate?: string;
      };
    };
  };
}

const initialState: JobsState = {
  byCompany: {},
};

const jobsSlice = createSlice({
  name: 'jobs',
  initialState,
  reducers: {
    clearJobs(state, action) {
      const companyId = action.payload;
      if (state.byCompany[companyId]) {
        state.byCompany[companyId].items = [];
        state.byCompany[companyId].metadata = {
          totalCount: 0,
          softwareCount: 0,
        };
      }
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadJobsForCompany.pending, (state, action) => {
        const { companyId } = action.meta.arg;
        if (!state.byCompany[companyId]) {
          state.byCompany[companyId] = {
            items: [],
            isLoading: true,
            error: undefined,
            metadata: { totalCount: 0, softwareCount: 0 },
          };
        } else {
          state.byCompany[companyId].isLoading = true;
          state.byCompany[companyId].error = undefined;
        }
      })
      .addCase(loadJobsForCompany.fulfilled, (state, action) => {
        const { companyId, jobs, metadata } = action.payload;

        state.byCompany[companyId] = {
          items: jobs,
          isLoading: false,
          error: undefined,
          lastFetchedAt: new Date().toISOString(),
          metadata,
        };
      })
      .addCase(loadJobsForCompany.rejected, (state, action) => {
        const { companyId } = action.meta.arg;
        if (!state.byCompany[companyId]) {
          state.byCompany[companyId] = {
            items: [],
            isLoading: false,
            error: action.error.message || 'Failed to load jobs',
            metadata: { totalCount: 0, softwareCount: 0 },
          };
        } else {
          state.byCompany[companyId].isLoading = false;
          state.byCompany[companyId].error = action.error.message || 'Failed to load jobs';
        }
      });
  },
});

export const { clearJobs } = jobsSlice.actions;
export default jobsSlice.reducer;
