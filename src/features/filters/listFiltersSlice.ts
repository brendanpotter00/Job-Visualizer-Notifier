import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { ListFilters, TimeWindow, SoftwareRoleCategory, SearchTag } from '../../types';
import {
  SOFTWARE_ENGINEERING_TAGS,
  getSoftwareEngineeringTagTexts,
} from '../../constants/softwareEngineeringTags';

/**
 * List filter state
 */
export interface ListFiltersState {
  filters: ListFilters;
}

const initialState: ListFiltersState = {
  filters: {
    timeWindow: '30d',
    searchTags: undefined,
    softwareOnly: false,
    roleCategory: undefined,
  },
};

const listFiltersSlice = createSlice({
  name: 'listFilters',
  initialState,
  reducers: {
    // Time window
    setListTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.filters.timeWindow = action.payload;
    },

    // Search tags
    setListSearchTags(state, action: PayloadAction<SearchTag[] | undefined>) {
      state.filters.searchTags = action.payload;
    },
    addListSearchTag(state, action: PayloadAction<SearchTag>) {
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
    removeListSearchTag(state, action: PayloadAction<string>) {
      if (!state.filters.searchTags) return;

      state.filters.searchTags = state.filters.searchTags.filter(
        (tag) => tag.text !== action.payload
      );

      if (state.filters.searchTags.length === 0) {
        state.filters.searchTags = undefined;
      }
    },
    toggleListSearchTagMode(state, action: PayloadAction<string>) {
      if (!state.filters.searchTags) return;

      const tag = state.filters.searchTags.find((t) => t.text === action.payload);
      if (tag) {
        tag.mode = tag.mode === 'include' ? 'exclude' : 'include';
      }
    },
    clearListSearchTags(state) {
      state.filters.searchTags = undefined;
    },

    // Location
    setListLocation(state, action: PayloadAction<string[] | undefined>) {
      state.filters.location = action.payload;
    },
    addListLocation(state, action: PayloadAction<string>) {
      const location = action.payload.trim();
      if (!location) return;

      if (!state.filters.location) {
        state.filters.location = [location];
      } else if (!state.filters.location.includes(location)) {
        state.filters.location.push(location);
      }
    },
    removeListLocation(state, action: PayloadAction<string>) {
      if (!state.filters.location) return;

      state.filters.location = state.filters.location.filter((loc) => loc !== action.payload);

      if (state.filters.location.length === 0) {
        state.filters.location = undefined;
      }
    },
    clearListLocations(state) {
      state.filters.location = undefined;
    },

    // Department
    addListDepartment(state, action: PayloadAction<string>) {
      const department = action.payload;

      if (!state.filters.department) {
        state.filters.department = [department];
      } else if (!state.filters.department.includes(department)) {
        state.filters.department.push(department);
      }
    },
    removeListDepartment(state, action: PayloadAction<string>) {
      if (!state.filters.department) return;

      state.filters.department = state.filters.department.filter((dept) => dept !== action.payload);

      if (state.filters.department.length === 0) {
        state.filters.department = undefined;
      }
    },
    clearListDepartments(state) {
      state.filters.department = undefined;
    },
    setListDepartment(state, action: PayloadAction<string[] | undefined>) {
      state.filters.department = action.payload;
    },

    // Employment type
    setListEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.filters.employmentType = action.payload;
    },

    // Role category
    addListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      const category = action.payload;

      if (!state.filters.roleCategory) {
        state.filters.roleCategory = [category];
      } else if (!state.filters.roleCategory.includes(category)) {
        state.filters.roleCategory.push(category);
      }
    },
    removeListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      if (!state.filters.roleCategory) return;

      state.filters.roleCategory = state.filters.roleCategory.filter(
        (cat) => cat !== action.payload
      );

      if (state.filters.roleCategory.length === 0) {
        state.filters.roleCategory = undefined;
      }
    },
    clearListRoleCategories(state) {
      state.filters.roleCategory = undefined;
    },
    setListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory[] | undefined>) {
      state.filters.roleCategory = action.payload;
    },

    // Software only - now manages search tags instead of boolean flag
    toggleListSoftwareOnly(state) {
      const seTagTexts = getSoftwareEngineeringTagTexts();
      const currentTags = state.filters.searchTags || [];

      // Check if all SE tags are present
      const allPresent = seTagTexts.every((text) =>
        currentTags.some((tag) => tag.text === text && tag.mode === 'include')
      );

      if (allPresent) {
        // Remove all SE tags (smart removal)
        state.filters.searchTags = currentTags.filter((tag) => !seTagTexts.includes(tag.text));
        if (state.filters.searchTags.length === 0) {
          state.filters.searchTags = undefined;
        }
      } else {
        // Add all SE tags
        const tagsToAdd = [...SOFTWARE_ENGINEERING_TAGS];
        const existingTexts = new Set(currentTags.map((tag) => tag.text));

        // Only add tags that don't already exist
        const newTags = tagsToAdd.filter((tag) => !existingTexts.has(tag.text));

        state.filters.searchTags = [...currentTags, ...newTags];
      }

      // Keep softwareOnly in sync for backwards compatibility
      state.filters.softwareOnly = !allPresent;
    },
    setListSoftwareOnly(state, action: PayloadAction<boolean>) {
      const seTagTexts = getSoftwareEngineeringTagTexts();
      const currentTags = state.filters.searchTags || [];

      if (action.payload) {
        // Add all SE tags
        const tagsToAdd = [...SOFTWARE_ENGINEERING_TAGS];
        const existingTexts = new Set(currentTags.map((tag) => tag.text));
        const newTags = tagsToAdd.filter((tag) => !existingTexts.has(tag.text));

        state.filters.searchTags = [...currentTags, ...newTags];
      } else {
        // Remove all SE tags
        state.filters.searchTags = currentTags.filter((tag) => !seTagTexts.includes(tag.text));
        if (state.filters.searchTags.length === 0) {
          state.filters.searchTags = undefined;
        }
      }

      state.filters.softwareOnly = action.payload;
    },

    // Reset
    resetListFilters(state) {
      state.filters = initialState.filters;
    },

    // Sync from graph (for cross-slice sync)
    syncListFromGraph(state, action: PayloadAction<ListFilters>) {
      state.filters = action.payload;
    },
  },
});

export const {
  setListTimeWindow,
  setListSearchTags,
  addListSearchTag,
  removeListSearchTag,
  toggleListSearchTagMode,
  clearListSearchTags,
  setListLocation,
  addListLocation,
  removeListLocation,
  clearListLocations,
  addListDepartment,
  removeListDepartment,
  clearListDepartments,
  setListDepartment,
  setListEmploymentType,
  addListRoleCategory,
  removeListRoleCategory,
  clearListRoleCategories,
  setListRoleCategory,
  toggleListSoftwareOnly,
  setListSoftwareOnly,
  resetListFilters,
  syncListFromGraph,
} = listFiltersSlice.actions;

export default listFiltersSlice.reducer;
