import { createSlice, createAsyncThunk, type PayloadAction } from '@reduxjs/toolkit';
import {
  fetchEnabledCompanies,
  updateEnabledCompanies,
  type EnabledCompaniesResult,
} from '../auth/authService';

export interface EnabledCompaniesState {
  ids: string[] | null;
  // Global "auto-include newly added companies" toggle. null until loaded.
  autoEnroll: boolean | null;
  loading: boolean;
  error: string | null;
  // requestId of the load whose fulfillment is still authoritative. Cleared
  // on save.pending so a load started before a save can't overwrite the
  // saved ids when it resolves afterwards.
  activeLoadRequestId: string | null;
}

const initialState: EnabledCompaniesState = {
  ids: null,
  autoEnroll: null,
  loading: false,
  error: null,
  activeLoadRequestId: null,
};

export const loadEnabledCompanies = createAsyncThunk<EnabledCompaniesResult, string>(
  'enabledCompanies/load',
  async (token, { signal }) => fetchEnabledCompanies(token, signal)
);

export const saveEnabledCompanies = createAsyncThunk<
  EnabledCompaniesResult,
  { token: string; companyIds: string[]; autoEnroll: boolean }
>('enabledCompanies/save', async ({ token, companyIds, autoEnroll }) =>
  updateEnabledCompanies(token, companyIds, autoEnroll)
);

const slice = createSlice({
  name: 'enabledCompanies',
  initialState,
  reducers: {
    reset: (state) => {
      state.ids = null;
      state.autoEnroll = null;
      state.loading = false;
      state.error = null;
      state.activeLoadRequestId = null;
    },
    // Synthetic rejection dispatched by the hook when token acquisition
    // fails before a load thunk can even start — surfaces the failure to
    // the UI instead of silently hanging.
    loadFailed: (state, action: PayloadAction<string>) => {
      state.loading = false;
      state.activeLoadRequestId = null;
      state.error = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder.addCase(loadEnabledCompanies.pending, (state, action) => {
      state.loading = true;
      state.error = null;
      state.activeLoadRequestId = action.meta.requestId;
    });
    builder.addCase(loadEnabledCompanies.fulfilled, (state, action) => {
      state.loading = false;
      // Skip stale loads: a save between pending and fulfilled cleared
      // activeLoadRequestId, so we must not clobber the fresh saved ids.
      if (state.activeLoadRequestId !== action.meta.requestId) return;
      state.ids = action.payload.companyIds;
      state.autoEnroll = action.payload.autoEnroll;
      state.activeLoadRequestId = null;
    });
    builder.addCase(loadEnabledCompanies.rejected, (state, action) => {
      // Always clear the pending spinner; skip writing error state on abort so a
      // stale fetch (e.g. sign-out mid-flight) doesn't clobber the real reason
      // the load ended.
      state.loading = false;
      if (state.activeLoadRequestId === action.meta.requestId) {
        state.activeLoadRequestId = null;
      }
      if (action.meta.aborted || action.error.name === 'AbortError') return;
      state.error = action.error.message ?? 'Failed to load enabled companies';
    });
    builder.addCase(saveEnabledCompanies.pending, (state) => {
      // Invalidate any in-flight load; its fulfilled handler checks the
      // active request id and will skip.
      state.activeLoadRequestId = null;
    });
    builder.addCase(saveEnabledCompanies.fulfilled, (state, action) => {
      state.ids = action.payload.companyIds;
      state.autoEnroll = action.payload.autoEnroll;
      state.error = null;
    });
    builder.addCase(saveEnabledCompanies.rejected, (state, action) => {
      if (action.meta.aborted || action.error.name === 'AbortError') return;
      state.error = action.error.message ?? 'Failed to save enabled companies';
    });
  },
});

export const {
  reset: resetEnabledCompanies,
  loadFailed: enabledCompaniesLoadFailed,
} = slice.actions;
export default slice.reducer;

export const selectEnabledCompanyIds = (state: {
  enabledCompanies: EnabledCompaniesState;
}) => state.enabledCompanies.ids;

export const selectAutoEnroll = (state: {
  enabledCompanies: EnabledCompaniesState;
}) => state.enabledCompanies.autoEnroll;
