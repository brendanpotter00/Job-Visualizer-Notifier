import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store.ts';
import type { LocationCatalogEntry } from '../filters/utils/jobFilteringUtils.ts';
import type { LocationSearchResult } from './locationsApi.ts';

/**
 * Session cache of `canonicalName -> structured fields` for every location the
 * user has selected from the server-side location search. It is seeded ONLY on
 * selection (not on every keystroke), so it changes reference exactly when the
 * location filter itself changes — the filtered-jobs selectors that read it
 * therefore never recompute merely because the user is typing in the dropdown.
 *
 * The job-location filter reads this via `selectLocationCatalog` and seeds it
 * into its `LocationIndex` so a picked location filters correctly even when no
 * currently-loaded job carries that exact tag (see `mergeCatalogIntoIndex`).
 */
export interface LocationCatalogState {
  byName: Record<string, LocationCatalogEntry>;
}

const initialState: LocationCatalogState = { byName: {} };

const locationCatalogSlice = createSlice({
  name: 'locationCatalog',
  initialState,
  reducers: {
    upsertLocationDescriptors: (state, action: PayloadAction<LocationSearchResult[]>) => {
      for (const row of action.payload) {
        state.byName[row.canonicalName] = {
          kind: row.kind,
          city: row.city,
          region: row.region,
          country: row.country,
          remoteScope: row.remoteScope,
        };
      }
    },
  },
});

export const { upsertLocationDescriptors } = locationCatalogSlice.actions;

/** Stable empty catalog so selectors reading a store without this slice
 * registered (e.g. minimal test stores) still return a reference-stable value. */
const EMPTY_CATALOG: Record<string, LocationCatalogEntry> = {};

export const selectLocationCatalog = (state: RootState): Record<string, LocationCatalogEntry> =>
  state.locationCatalog?.byName ?? EMPTY_CATALOG;

export default locationCatalogSlice.reducer;
