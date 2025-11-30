import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { ATSProvider } from '../../types';
import { ATSConstants } from '../../api/types.ts';

/**
 * Application-level state
 */
export interface AppState {
  /** Currently selected company */
  selectedCompanyId: string;

  /** Current view type (derived from company.ats) */
  selectedATS: ATSProvider;

  /** App initialization status */
  isInitialized: boolean;
}

const initialState: AppState = {
  selectedCompanyId: 'spacex', // Default to SpaceX
  selectedATS: ATSConstants.Greenhouse,
  isInitialized: false,
};

const appSlice = createSlice({
  name: 'app',
  initialState,
  reducers: {
    setSelectedCompanyId(state, action: PayloadAction<string>) {
      state.selectedCompanyId = action.payload;
    },
    setSelectedATS(state, action: PayloadAction<ATSProvider>) {
      state.selectedATS = action.payload;
    },
    setInitialized(state) {
      state.isInitialized = true;
    },
  },
});

export const { setSelectedCompanyId, setSelectedATS, setInitialized } = appSlice.actions;
export default appSlice.reducer;
