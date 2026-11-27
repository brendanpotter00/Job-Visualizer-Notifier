import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

/**
 * The outcome of the last "Save default search", keyed by the search it saved
 * (`defaultSearchKey`), so the button can show "Saved default search" only while
 * the live filters still ARE that search.
 *
 * Its own slice rather than a field on `ui`: many tests preload a partial `ui`,
 * and a new required field there would break them. Reset on sign-out
 * (`useHydrateSavedFilters`).
 */
export interface DefaultSearchResult {
  kind: 'saved' | 'error';
  key: string;
  message?: string;
}

export interface DefaultSearchState {
  saving: boolean;
  result: DefaultSearchResult | null;
}

const initialState: DefaultSearchState = { saving: false, result: null };

const defaultSearchSlice = createSlice({
  name: 'defaultSearch',
  initialState,
  reducers: {
    saveStarted(state) {
      state.saving = true;
      state.result = null;
    },
    saveSucceeded(state, action: PayloadAction<string>) {
      state.saving = false;
      state.result = { kind: 'saved', key: action.payload };
    },
    saveFailed(state, action: PayloadAction<{ key: string; message: string }>) {
      state.saving = false;
      state.result = { kind: 'error', key: action.payload.key, message: action.payload.message };
    },
    resetDefaultSearch() {
      return initialState;
    },
  },
});

export const { saveStarted, saveSucceeded, saveFailed, resetDefaultSearch } =
  defaultSearchSlice.actions;

export default defaultSearchSlice.reducer;
