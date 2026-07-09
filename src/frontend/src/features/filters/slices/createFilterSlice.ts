import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import type {
  GraphFilters,
  ListFilters,
  RecentJobsFilters,
  TimeWindow,
  SearchTag,
} from '../../../types';
import {
  setSearchTags as setSearchTagsUtil,
  addSearchTagToFilters,
  removeSearchTagFromFilters,
  toggleSearchTagMode as toggleSearchTagModeUtil,
  clearSearchTags as clearSearchTagsUtil,
  setLocations,
  addLocationToFilters,
  removeLocationFromFilters,
  clearLocations as clearLocationsUtil,
  setDepartments,
  addDepartmentToFilters,
  removeDepartmentFromFilters,
  clearDepartments as clearDepartmentsUtil,
  toggleSoftwareOnlyInFilters,
  setSoftwareOnlyInFilters,
} from '../utils/filterReducerUtils';

/**
 * Type for filter slice name
 */
export type FilterSliceName = 'graph' | 'list' | 'recentJobs';

/**
 * Union type for all filter types
 */
export type Filters = GraphFilters | ListFilters | RecentJobsFilters;

/**
 * Subset of `Filters` that owns a `department?: string[]` field.
 * Matches `GraphFilters` and `ListFilters`; excludes `RecentJobsFilters`.
 */
type FiltersWithDepartments = GraphFilters | ListFilters;

/**
 * Subset of `Filters` that owns a `company?: string[]` field.
 * Matches `RecentJobsFilters`; excludes the graph/list variants.
 */
type FiltersWithCompany = RecentJobsFilters;

/**
 * Slice-name-based guard: narrows a `Filters` (or draft thereof) to a
 * variant that carries a `department` field. The runtime decision is based
 * on the slice's `name` (captured in closure at factory-instantiation
 * time), which maps 1:1 to the concrete filter shape: `graph` and `list`
 * own `department`, `recentJobs` does not. The structural alternative
 * (`'department' in filters`) would false-negative on literal initial-state
 * objects that omit the optional key, so we key off `name` instead.
 */
function hasDepartmentField<T extends Filters>(
  name: FilterSliceName,
  filters: T
): filters is T & FiltersWithDepartments {
  void filters;
  return name === 'graph' || name === 'list';
}

/**
 * Slice-name-based guard: narrows a `Filters` (or draft thereof) to a
 * variant that carries a `company` field. Only `recentJobs` slices own
 * `company`; `graph` and `list` do not. Used by the recent-jobs reducers.
 */
function hasCompanyField<T extends Filters>(
  name: FilterSliceName,
  filters: T
): filters is T & FiltersWithCompany {
  void filters;
  return name === 'recentJobs';
}

/**
 * Filter state structure.
 *
 * `hydrated` guards the one-time hydration from saved filters (see the
 * `hydrate{Name}Filters` reducer). Once true, saved-filters hydration is a no-op so
 * later user edits to the filters are never clobbered by a re-run of the
 * hydration effect. It is reset to false on logout via `set{Name}Hydrated`.
 *
 * `userModified` becomes true the moment the user changes any filter in this
 * slice (set/add/remove/toggle/clear of any field). It exists to close a race:
 * the saved-filters queries can resolve *seconds* after mount on a cold-started
 * backend, so a signed-in user can edit the filters (e.g. add a keyword) BEFORE
 * the first hydration runs. `hydrated` is still false at that point, so without
 * this flag the late hydration would `Object.assign` the saved defaults over the
 * user's in-progress edit and silently discard it. Hydration therefore treats a
 * `userModified` slice as off-limits. Reset clears it (next sign-in re-hydrates).
 */
export interface FiltersState<T extends Filters> {
  filters: T;
  hydrated: boolean;
  userModified: boolean;
}

/**
 * Capitalize first letter of string
 */
function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Factory function to create filter slices with identical logic.
 *
 * This eliminates duplication across the graph and recent-jobs filter slices
 * by generating all filter action creators dynamically.
 *
 * @example
 * ```typescript
 * const graphFiltersSlice = createFilterSlice('graph', {
 *   timeWindow: '7d',
 *   searchTags: undefined,
 *   softwareOnly: false,
 * });
 * ```
 *
 * @param name - 'graph', 'list', or 'recentJobs'
 * @param initialFilters - Initial filter values
 * @returns Redux Toolkit slice with all filter actions
 */
export function createFilterSlice<T extends Filters>(name: FilterSliceName, initialFilters: T) {
  const capitalizedName = capitalize(name);

  const initialState: FiltersState<T> = {
    filters: initialFilters,
    hydrated: false,
    userModified: false,
  };

  const slice = createSlice({
    name: `${name}Filters`,
    initialState,
    reducers: {
      // Time window
      [`set${capitalizedName}TimeWindow`]: (state, action: PayloadAction<TimeWindow>) => {
        state.filters.timeWindow = action.payload;
      },

      // Search tags (5 actions)
      [`set${capitalizedName}SearchTags`]: (
        state,
        action: PayloadAction<SearchTag[] | undefined>
      ) => {
        setSearchTagsUtil(state.filters, action.payload);
      },
      [`add${capitalizedName}SearchTag`]: (state, action: PayloadAction<SearchTag>) => {
        addSearchTagToFilters(state.filters, action.payload);
      },
      [`remove${capitalizedName}SearchTag`]: (state, action: PayloadAction<string>) => {
        removeSearchTagFromFilters(state.filters, action.payload);
      },
      [`toggle${capitalizedName}SearchTagMode`]: (state, action: PayloadAction<string>) => {
        toggleSearchTagModeUtil(state.filters, action.payload);
      },
      [`clear${capitalizedName}SearchTags`]: (state) => {
        clearSearchTagsUtil(state.filters);
      },

      // Location (4 actions)
      [`set${capitalizedName}Location`]: (state, action: PayloadAction<string[] | undefined>) => {
        setLocations(state.filters, action.payload);
      },
      [`add${capitalizedName}Location`]: (state, action: PayloadAction<string>) => {
        addLocationToFilters(state.filters, action.payload);
      },
      [`remove${capitalizedName}Location`]: (state, action: PayloadAction<string>) => {
        removeLocationFromFilters(state.filters, action.payload);
      },
      [`clear${capitalizedName}Locations`]: (state) => {
        clearLocationsUtil(state.filters);
      },

      // Department (4 actions)
      [`add${capitalizedName}Department`]: (state, action: PayloadAction<string>) => {
        if (hasDepartmentField(name, state.filters)) {
          addDepartmentToFilters(state.filters, action.payload);
        }
      },
      [`remove${capitalizedName}Department`]: (state, action: PayloadAction<string>) => {
        if (hasDepartmentField(name, state.filters)) {
          removeDepartmentFromFilters(state.filters, action.payload);
        }
      },
      [`clear${capitalizedName}Departments`]: (state) => {
        if (hasDepartmentField(name, state.filters)) {
          clearDepartmentsUtil(state.filters);
        }
      },
      [`set${capitalizedName}Department`]: (state, action: PayloadAction<string[] | undefined>) => {
        if (hasDepartmentField(name, state.filters)) {
          setDepartments(state.filters, action.payload);
        }
      },

      // Employment type (1 action)
      [`set${capitalizedName}EmploymentType`]: (
        state,
        action: PayloadAction<string | undefined>
      ) => {
        state.filters.employmentType = action.payload;
      },

      // Enrichment facets (2 actions). Single-value slugs; `undefined` clears
      // (the "All" option). Every filter shape owns both fields, so no
      // slice-name guard is needed (unlike department/company).
      [`set${capitalizedName}Category`]: (state, action: PayloadAction<string | undefined>) => {
        state.filters.category = action.payload;
      },
      [`set${capitalizedName}Level`]: (state, action: PayloadAction<string | undefined>) => {
        state.filters.level = action.payload;
      },

      // Company (4 actions)
      [`set${capitalizedName}Company`]: (state, action: PayloadAction<string[] | undefined>) => {
        if (hasCompanyField(name, state.filters)) {
          state.filters.company = action.payload;
        }
      },
      [`add${capitalizedName}Company`]: (state, action: PayloadAction<string>) => {
        if (!hasCompanyField(name, state.filters)) return;
        const filters = state.filters;
        if (!filters.company) {
          filters.company = [];
        }
        if (!filters.company.includes(action.payload)) {
          filters.company.push(action.payload);
        }
      },
      [`remove${capitalizedName}Company`]: (state, action: PayloadAction<string>) => {
        if (!hasCompanyField(name, state.filters)) return;
        const filters = state.filters;
        if (filters.company) {
          filters.company = filters.company.filter((c) => c !== action.payload);
          if (filters.company.length === 0) {
            filters.company = undefined;
          }
        }
      },
      [`clear${capitalizedName}Companies`]: (state) => {
        if (hasCompanyField(name, state.filters)) {
          state.filters.company = undefined;
        }
      },

      // Software only (2 actions) - manages search tags instead of boolean flag
      [`toggle${capitalizedName}SoftwareOnly`]: (state) => {
        toggleSoftwareOnlyInFilters(state.filters);
      },
      [`set${capitalizedName}SoftwareOnly`]: (state, action: PayloadAction<boolean>) => {
        setSoftwareOnlyInFilters(state.filters, action.payload);
      },

      // Hydration from saved filters (2 actions)
      //
      // `hydrate{Name}Filters` applies saved filter values ONCE. The payload is a
      // partial so only the saved-filter-backed fields (timeWindow, location,
      // searchTags) are overwritten.
      //
      // Two guards, both required:
      //   1. `hydrated` — a re-running effect (or a second mount) is a no-op.
      //   2. `userModified` — if the user already edited this slice before the
      //      (possibly cold-started) saved-filters queries resolved, DON'T
      //      overwrite their in-progress edits with the saved defaults. Without
      //      this, a late hydration silently wiped a just-added keyword on the
      //      Recent Jobs / Company pages. We still mark `hydrated` so the effect
      //      won't keep retrying, but we seed nothing.
      [`hydrate${capitalizedName}Filters`]: (state, action: PayloadAction<Partial<T>>) => {
        if (state.hydrated) return;
        state.hydrated = true;
        if (state.userModified) return;
        Object.assign(state.filters, action.payload);
      },
      [`set${capitalizedName}Hydrated`]: (state, action: PayloadAction<boolean>) => {
        state.hydrated = action.payload;
      },

      // Reset (1 action)
      [`reset${capitalizedName}Filters`]: (state) => {
        // Use Object.assign to work with Immer's Draft type
        Object.assign(state.filters, initialState.filters);
        // Clear the user-edit flag so a subsequent sign-in re-hydrates from the
        // (new) user's saved filters rather than treating the slice as touched.
        state.userModified = false;
      },
    },
    extraReducers: (builder) => {
      // Any user-initiated edit to this slice flips `userModified`, which makes a
      // late saved-filters hydration a no-op (see the hydrate reducer). The matcher
      // is allow-by-DEFAULT: it flips the flag for EVERY action under
      // `${name}Filters/` EXCEPT the non-edit actions listed in `nonEditTypes`
      // (hydration / the hydrated flag / reset). Using a matcher keeps this DRY
      // across all generated edit reducers.
      //
      // MAINTENANCE INVARIANT: this is correct only while every NON-edit action on
      // this slice is listed in `nonEditTypes`. A new EDIT action is covered for
      // free. But a new NON-edit action (e.g. a loading/error/another-flag setter)
      // MUST be added to `nonEditTypes` too — otherwise it is wrongly treated as a
      // user edit and silently suppresses saved-filters hydration.
      const slicePrefix = `${name}Filters/`;
      const nonEditTypes = new Set<string>([
        `${slicePrefix}hydrate${capitalizedName}Filters`,
        `${slicePrefix}set${capitalizedName}Hydrated`,
        `${slicePrefix}reset${capitalizedName}Filters`,
      ]);
      builder.addMatcher(
        (action): action is { type: string } =>
          typeof (action as { type?: unknown }).type === 'string' &&
          (action as { type: string }).type.startsWith(slicePrefix) &&
          !nonEditTypes.has((action as { type: string }).type),
        (state) => {
          state.userModified = true;
        }
      );
    },
  });

  // Return the slice - TypeScript will infer action types from the actual implementation
  return slice;
}
