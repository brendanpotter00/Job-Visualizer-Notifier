import { loadJobsForCompany } from '../jobs/jobsThunks.ts';
import { createSlice } from '@reduxjs/toolkit';
import { Job } from '../../types';

interface AllJobsState {
  byCompanyId: Record<string, Job[]>;
  // ... other state like loading/error
}

const initialState: AllJobsState = {
  byCompanyId: {},
};

const allJobsSlice = createSlice({
  name: 'jobs',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder.addCase(loadJobsForCompany.fulfilled, (state, action) => {
      const { companyId, jobs } = action.payload;
      state.byCompanyId[companyId] = jobs;
    });
  },
});

export default allJobsSlice.reducer;
