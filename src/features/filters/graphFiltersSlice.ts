import type { GraphFilters } from '../../types';
import { createFilterSlice } from './createFilterSlice';

/**
 * Graph filter state
 */
export interface GraphFiltersState {
  filters: GraphFilters;
}

const initialFilters: GraphFilters = {
  timeWindow: '30d',
  searchTags: undefined,
  softwareOnly: false,
  roleCategory: undefined,
};

const graphFiltersSlice = createFilterSlice('graph', initialFilters);

// Extract actions with proper typing
// TypeScript can't infer action types from computed property names, so we cast here
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
} = graphFiltersSlice.actions as any;

export default graphFiltersSlice.reducer;
