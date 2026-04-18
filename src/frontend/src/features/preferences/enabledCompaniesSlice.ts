import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { fetchEnabledCompanies, updateEnabledCompanies } from '../auth/authService';

export interface EnabledCompaniesState {
  ids: string[] | null;
  loading: boolean;
  error: string | null;
}

const initialState: EnabledCompaniesState = {
  ids: null,
  loading: false,
  error: null,
};

export const loadEnabledCompanies = createAsyncThunk<string[], string>(
  'enabledCompanies/load',
  async (token, { signal }) => fetchEnabledCompanies(token, signal)
);

export const saveEnabledCompanies = createAsyncThunk<
  string[],
  { token: string; companyIds: string[] }
>('enabledCompanies/save', async ({ token, companyIds }) =>
  updateEnabledCompanies(token, companyIds)
);

const slice = createSlice({
  name: 'enabledCompanies',
  initialState,
  reducers: {
    reset: (state) => {
      state.ids = null;
      state.loading = false;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder.addCase(loadEnabledCompanies.pending, (state) => {
      state.loading = true;
      state.error = null;
    });
    builder.addCase(loadEnabledCompanies.fulfilled, (state, action) => {
      state.loading = false;
      state.ids = action.payload;
    });
    builder.addCase(loadEnabledCompanies.rejected, (state, action) => {
      // Always clear the pending spinner; skip writing error state on abort so a
      // stale fetch (e.g. sign-out mid-flight) doesn't clobber the real reason
      // the load ended.
      state.loading = false;
      if (action.meta.aborted || action.error.name === 'AbortError') return;
      state.error = action.error.message ?? 'Failed to load enabled companies';
    });
    builder.addCase(saveEnabledCompanies.fulfilled, (state, action) => {
      state.ids = action.payload;
      state.error = null;
    });
    builder.addCase(saveEnabledCompanies.rejected, (state, action) => {
      if (action.meta.aborted || action.error.name === 'AbortError') return;
      state.error = action.error.message ?? 'Failed to save enabled companies';
    });
  },
});

export const { reset: resetEnabledCompanies } = slice.actions;
export default slice.reducer;

export const selectEnabledCompanyIds = (state: {
  enabledCompanies: EnabledCompaniesState;
}) => state.enabledCompanies.ids;
