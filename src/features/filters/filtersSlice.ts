import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type { GraphFilters, ListFilters, TimeWindow, SoftwareRoleCategory, SearchTag } from '../../types';

/**
 * Filter state (graph and list are independent)
 */
export interface FiltersState {
  graph: GraphFilters;
  list: ListFilters;
}

const initialState: FiltersState = {
  graph: {
    timeWindow: '30d',
    searchTags: undefined,
    softwareOnly: false,
    roleCategory: undefined,
  },
  list: {
    timeWindow: '30d',
    searchTags: undefined,
    softwareOnly: false,
    roleCategory: undefined,
  },
};

const filtersSlice = createSlice({
  name: 'filters',
  initialState,
  reducers: {
    // Graph filters
    setGraphTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.graph.timeWindow = action.payload;
    },
    setGraphSearchTags(state, action: PayloadAction<SearchTag[] | undefined>) {
      state.graph.searchTags = action.payload;
    },
    addGraphSearchTag(state, action: PayloadAction<SearchTag>) {
      const trimmedText = action.payload.text.trim();
      if (!trimmedText) return;

      const tag = { text: trimmedText, mode: action.payload.mode };

      if (!state.graph.searchTags) {
        state.graph.searchTags = [tag];
      } else {
        const exists = state.graph.searchTags.some(t => t.text === tag.text);
        if (!exists) {
          state.graph.searchTags.push(tag);
        }
      }
    },
    removeGraphSearchTag(state, action: PayloadAction<string>) {
      if (!state.graph.searchTags) return;

      state.graph.searchTags = state.graph.searchTags.filter(
        tag => tag.text !== action.payload
      );

      if (state.graph.searchTags.length === 0) {
        state.graph.searchTags = undefined;
      }
    },
    toggleGraphSearchTagMode(state, action: PayloadAction<string>) {
      if (!state.graph.searchTags) return;

      const tag = state.graph.searchTags.find(t => t.text === action.payload);
      if (tag) {
        tag.mode = tag.mode === 'include' ? 'exclude' : 'include';
      }
    },
    clearGraphSearchTags(state) {
      state.graph.searchTags = undefined;
    },
    setGraphLocation(state, action: PayloadAction<string[] | undefined>) {
      state.graph.location = action.payload;
    },
    addGraphLocation(state, action: PayloadAction<string>) {
      const location = action.payload.trim();
      if (!location) return;

      if (!state.graph.location) {
        state.graph.location = [location];
      } else if (!state.graph.location.includes(location)) {
        state.graph.location.push(location);
      }
    },
    removeGraphLocation(state, action: PayloadAction<string>) {
      if (!state.graph.location) return;

      state.graph.location = state.graph.location.filter(
        loc => loc !== action.payload
      );

      if (state.graph.location.length === 0) {
        state.graph.location = undefined;
      }
    },
    clearGraphLocations(state) {
      state.graph.location = undefined;
    },
    addGraphDepartment(state, action: PayloadAction<string>) {
      const department = action.payload;

      if (!state.graph.department) {
        state.graph.department = [department];
      } else if (!state.graph.department.includes(department)) {
        state.graph.department.push(department);
      }
    },
    removeGraphDepartment(state, action: PayloadAction<string>) {
      if (!state.graph.department) return;

      state.graph.department = state.graph.department.filter(
        dept => dept !== action.payload
      );

      if (state.graph.department.length === 0) {
        state.graph.department = undefined;
      }
    },
    clearGraphDepartments(state) {
      state.graph.department = undefined;
    },
    setGraphEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.graph.employmentType = action.payload;
    },
    addGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      const category = action.payload;

      if (!state.graph.roleCategory) {
        state.graph.roleCategory = [category];
      } else if (!state.graph.roleCategory.includes(category)) {
        state.graph.roleCategory.push(category);
      }
    },
    removeGraphRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      if (!state.graph.roleCategory) return;

      state.graph.roleCategory = state.graph.roleCategory.filter(
        cat => cat !== action.payload
      );

      if (state.graph.roleCategory.length === 0) {
        state.graph.roleCategory = undefined;
      }
    },
    clearGraphRoleCategories(state) {
      state.graph.roleCategory = undefined;
    },
    toggleGraphSoftwareOnly(state) {
      state.graph.softwareOnly = !state.graph.softwareOnly;
    },
    resetGraphFilters(state) {
      state.graph = initialState.graph;
    },

    // List filters
    setListTimeWindow(state, action: PayloadAction<TimeWindow>) {
      state.list.timeWindow = action.payload;
    },
    setListSearchTags(state, action: PayloadAction<SearchTag[] | undefined>) {
      state.list.searchTags = action.payload;
    },
    addListSearchTag(state, action: PayloadAction<SearchTag>) {
      const trimmedText = action.payload.text.trim();
      if (!trimmedText) return;

      const tag = { text: trimmedText, mode: action.payload.mode };

      if (!state.list.searchTags) {
        state.list.searchTags = [tag];
      } else {
        const exists = state.list.searchTags.some(t => t.text === tag.text);
        if (!exists) {
          state.list.searchTags.push(tag);
        }
      }
    },
    removeListSearchTag(state, action: PayloadAction<string>) {
      if (!state.list.searchTags) return;

      state.list.searchTags = state.list.searchTags.filter(
        tag => tag.text !== action.payload
      );

      if (state.list.searchTags.length === 0) {
        state.list.searchTags = undefined;
      }
    },
    toggleListSearchTagMode(state, action: PayloadAction<string>) {
      if (!state.list.searchTags) return;

      const tag = state.list.searchTags.find(t => t.text === action.payload);
      if (tag) {
        tag.mode = tag.mode === 'include' ? 'exclude' : 'include';
      }
    },
    clearListSearchTags(state) {
      state.list.searchTags = undefined;
    },
    setListLocation(state, action: PayloadAction<string[] | undefined>) {
      state.list.location = action.payload;
    },
    addListLocation(state, action: PayloadAction<string>) {
      const location = action.payload.trim();
      if (!location) return;

      if (!state.list.location) {
        state.list.location = [location];
      } else if (!state.list.location.includes(location)) {
        state.list.location.push(location);
      }
    },
    removeListLocation(state, action: PayloadAction<string>) {
      if (!state.list.location) return;

      state.list.location = state.list.location.filter(
        loc => loc !== action.payload
      );

      if (state.list.location.length === 0) {
        state.list.location = undefined;
      }
    },
    clearListLocations(state) {
      state.list.location = undefined;
    },
    addListDepartment(state, action: PayloadAction<string>) {
      const department = action.payload;

      if (!state.list.department) {
        state.list.department = [department];
      } else if (!state.list.department.includes(department)) {
        state.list.department.push(department);
      }
    },
    removeListDepartment(state, action: PayloadAction<string>) {
      if (!state.list.department) return;

      state.list.department = state.list.department.filter(
        dept => dept !== action.payload
      );

      if (state.list.department.length === 0) {
        state.list.department = undefined;
      }
    },
    clearListDepartments(state) {
      state.list.department = undefined;
    },
    setListEmploymentType(state, action: PayloadAction<string | undefined>) {
      state.list.employmentType = action.payload;
    },
    addListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      const category = action.payload;

      if (!state.list.roleCategory) {
        state.list.roleCategory = [category];
      } else if (!state.list.roleCategory.includes(category)) {
        state.list.roleCategory.push(category);
      }
    },
    removeListRoleCategory(state, action: PayloadAction<SoftwareRoleCategory>) {
      if (!state.list.roleCategory) return;

      state.list.roleCategory = state.list.roleCategory.filter(
        cat => cat !== action.payload
      );

      if (state.list.roleCategory.length === 0) {
        state.list.roleCategory = undefined;
      }
    },
    clearListRoleCategories(state) {
      state.list.roleCategory = undefined;
    },
    toggleListSoftwareOnly(state) {
      state.list.softwareOnly = !state.list.softwareOnly;
    },
    resetListFilters(state) {
      state.list = initialState.list;
    },

    // Reset all filters
    resetAllFilters(state) {
      state.graph = initialState.graph;
      state.list = initialState.list;
    },
  },
});

export const {
  // Graph actions
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
  setGraphEmploymentType,
  addGraphRoleCategory,
  removeGraphRoleCategory,
  clearGraphRoleCategories,
  toggleGraphSoftwareOnly,
  resetGraphFilters,
  // List actions
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
  setListEmploymentType,
  addListRoleCategory,
  removeListRoleCategory,
  clearListRoleCategories,
  toggleListSoftwareOnly,
  resetListFilters,
  // Combined
  resetAllFilters,
} = filtersSlice.actions;

export default filtersSlice.reducer;
