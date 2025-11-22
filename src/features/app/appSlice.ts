import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { ATSProvider } from '../../types';

/**
 * Application-level state
 */
export interface AppState {
  /** Currently selected company */
  selectedCompanyId: string;

  /** Current view type (derived from company.ats) */
  selectedView: ATSProvider;

  /** App initialization status */
  isInitialized: boolean;
}

const initialState: AppState = {
  selectedCompanyId: 'spacex', // Default to SpaceX
  selectedView: 'greenhouse',
  isInitialized: false,
};

const appSlice = createSlice({
  name: 'app',
  initialState,
  reducers: {
    selectCompany(state, action: PayloadAction<string>) {
      state.selectedCompanyId = action.payload;
    },
    setSelectedView(state, action: PayloadAction<ATSProvider>) {
      state.selectedView = action.payload;
    },
    setInitialized(state) {
      state.isInitialized = true;
    },
  },
});

export const { selectCompany, setSelectedView, setInitialized } = appSlice.actions;
export default appSlice.reducer;
