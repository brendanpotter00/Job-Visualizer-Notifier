import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { GraphFilters, TimeWindow, SoftwareRoleCategory, SearchTag } from '../../types';

/**
 * Graph filter state
 */
export interface GraphFiltersState {
  filters: GraphFilters;
}

const initialState: GraphFiltersState = {
  filters: {
    timeWindow: '30d',
    searchTags: undefined,
    softwareOnly: false,
    roleCategory: undefined,
  },
};

const graphFiltersSlice = createSlice({
  name: 'graphFilters',
  initialState,
  reducers: {
    // Time window
    setGraphTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.filters.timeWindow = action.payload;
    },

    // Search tags
    setGraphSearchTags(state, action: PayloadAction<SearchTag[] | undefined>) {
      state.filters.searchTags = action.payload;
    },
    addGraphSearchTag(state, action: PayloadAction<SearchTag>) {
      const trimmedText = action.payload.text.trim();
      if (!trimmedText) return;

      const tag = { text: trimmedText, mode: action.payload.mode };

      if (!state.filters.searchTags) {
        state.filters.searchTags = [tag];
      } else {
        const exists = state.filters.searchTags.some((t) => t.text === tag.text);
        if (!exists) {
          state.filters.searchTags.push(tag);
        }
      }
    },
    removeGraphSearchTag(state, action: PayloadAction<string>) {
      if (!state.filters.searchTags) return;

      state.filters.searchTags = state.filters.searchTags.filter((tag) => tag.text !== action.payload);

      if (state.filters.searchTags.length === 0) {
        state.filters.searchTags = undefined;
      }
    },
    toggleGraphSearchTagMode(state, action: PayloadAction<string>) {
      if (!state.filters.searchTags) return;

      const tag = state.filters.searchTags.find((t) => t.text === action.payload);
      if (tag) {
        tag.mode = tag.mode === 'include' ? 'exclude' : 'include';
      }
    },
    clearGraphSearchTags(state) {
      state.filters.searchTags = undefined;
    },

    // Location
    setGraphLocation(state, action: PayloadAction<string[] | undefined>) {
      state.filters.location = action.payload;
    },
    addGraphLocation(state, action: PayloadAction<string>) {
      const location = action.payload.trim();
      if (!location) return;

      if (!state.filters.location) {
        state.filters.location = [location];
      } else if (!state.filters.location.includes(location)) {
        state.filters.location.push(location);
      }
    },
    removeGraphLocation(state, action: PayloadAction<string>) {
      if (!state.filters.location) return;

      state.filters.location = state.filters.location.filter((loc) => loc !== action.payload);

      if (state.filters.location.length === 0) {
        state.filters.location = undefined;
      }
    },
    clearGraphLocations(state) {
      state.filters.location = undefined;
    },

    // Department
    addGraphDepartment(state, action: PayloadAction<string>) {
      const department = action.payload;

      if (!state.filters.department) {
        state.filters.department = [department];
      } else if (!state.filters.department.includes(department)) {
        state.filters.department.push(department);
      }
    },
    removeGraphDepartment(state, action: PayloadAction<string>) {
      if (!state.filters.department) return;

      state.filters.department = state.filters.department.filter((dept) => dept !== action.payload);

      if (state.filters.department.length === 0) {
        state.filters.department = undefined;
      }
    },
    clearGraphDepartments(state) {
      state.filters.department = undefined;
    },
    setGraphDepartment(state, action: PayloadAction<string[] | undefined>) {
      state.filters.department = action.payload;
    },

    // Employment type
    setGraphEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.filters.employmentType = action.payload;
    },

    // Role category
    addGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      const category = action.payload;

      if (!state.filters.roleCategory) {
        state.filters.roleCategory = [category];
      } else if (!state.filters.roleCategory.includes(category)) {
        state.filters.roleCategory.push(category);
      }
    },
    removeGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      if (!state.filters.roleCategory) return;

      state.filters.roleCategory = state.filters.roleCategory.filter((cat) => cat !== action.payload);

      if (state.filters.roleCategory.length === 0) {
        state.filters.roleCategory = undefined;
      }
    },
    clearGraphRoleCategories(state) {
      state.filters.roleCategory = undefined;
    },
    setGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory[] | undefined>) {
      state.filters.roleCategory = action.payload;
    },

    // Software only
    toggleGraphSoftwareOnly(state) {
      state.filters.softwareOnly = !state.filters.softwareOnly;
    },
    setGraphSoftwareOnly(state, action: PayloadAction<boolean>) {
      state.filters.softwareOnly = action.payload;
    },

    // Reset
    resetGraphFilters(state) {
      state.filters = initialState.filters;
    },

    // Sync from list (for cross-slice sync)
    syncGraphFromList(state, action: PayloadAction<GraphFilters>) {
      state.filters = action.payload;
    },
  },
});

export const {
  setGraphTimeWindow,
  setGraphSearchTags,
  addGraphSearchTag,
  removeGraphSearchTag,
  toggleGraphSearchTagMode,
  clearGraphSearchTags,
  setGraphLocation,
  addGraphLocation,
  removeGraphLocation,
  clearGraphLocations,
  addGraphDepartment,
  removeGraphDepartment,
  clearGraphDepartments,
  setGraphDepartment,
  setGraphEmploymentType,
  addGraphRoleCategory,
  removeGraphRoleCategory,
  clearGraphRoleCategories,
  setGraphRoleCategory,
  toggleGraphSoftwareOnly,
  setGraphSoftwareOnly,
  resetGraphFilters,
  syncGraphFromList,
} = graphFiltersSlice.actions;

export default graphFiltersSlice.reducer;
