import { describe, it, expect } from 'vitest';
import { createFilterSlice, type FilterSliceName } from '../../../features/filters/slices/createFilterSlice';
import type {
  GraphFilters,
  ListFilters,
  RecentJobsFilters,
  TimeWindow,
} from '../../../types';

describe('createFilterSlice', () => {
  describe('Factory Pattern', () => {
    it('should create a slice with correct name for graph', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);

      expect(slice.name).toBe('graphFilters');
    });

    it('should create a slice with correct name for list', () => {
      const initialFilters: ListFilters = {
        timeWindow: '7d',
        searchTags: undefined,
        softwareOnly: true,
      };

      const slice = createFilterSlice('list', initialFilters);

      expect(slice.name).toBe('listFilters');
    });

    it('should have all expected actions', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const actionNames = Object.keys(slice.actions);

      // Verify all expected actions exist
      const expectedActions = [
        'setGraphTimeWindow',
        'setGraphSearchTags',
        'addGraphSearchTag',
        'removeGraphSearchTag',
        'toggleGraphSearchTagMode',
        'clearGraphSearchTags',
        'setGraphLocation',
        'addGraphLocation',
        'removeGraphLocation',
        'clearGraphLocations',
        'addGraphDepartment',
        'removeGraphDepartment',
        'clearGraphDepartments',
        'setGraphDepartment',
        'setGraphEmploymentType',
        'setGraphCategory',
        'setGraphLevel',
        'toggleGraphSoftwareOnly',
        'setGraphSoftwareOnly',
        'hydrateGraphFilters',
        'setGraphHydrated',
        'resetGraphFilters',
      ];

      expectedActions.forEach((actionName) => {
        expect(actionNames).toContain(actionName);
      });

      // 22 prior actions + hydrate{Name}Filters + set{Name}Hydrated
      // + set{Name}Category + set{Name}Level (enrichment facets)
      expect(actionNames).toHaveLength(26);
    });
  });

  describe('Reducer Behavior', () => {
    it('should set time window correctly', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphTimeWindow',
        payload: '7d' as TimeWindow,
      });

      expect(newState.filters.timeWindow).toBe('7d');
    });

    it('should reset filters to initial state', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);

      // Modify state
      let state = {
        filters: { ...initialFilters, timeWindow: '7d' as TimeWindow },
        hydrated: false,
        userModified: false,
      };

      // Reset
      const newState = slice.reducer(state, {
        type: 'graphFilters/resetGraphFilters',
        payload: undefined,
      });

      expect(newState.filters).toEqual(initialFilters);
    });

    it('should set employment type correctly', () => {
      const initialFilters: ListFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('list', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'listFilters/setListEmploymentType',
        payload: 'Full-time',
      });

      expect(newState.filters.employmentType).toBe('Full-time');
    });
  });

  describe('Action Naming Convention', () => {
    it('should capitalize action names correctly for graph', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const actionNames = Object.keys(slice.actions);

      // All actions should start with capital 'G' for Graph
      actionNames.forEach((name) => {
        expect(name).toMatch(/^[a-z]+Graph/);
      });
    });

    it('should capitalize action names correctly for list', () => {
      const initialFilters: ListFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('list', initialFilters);
      const actionNames = Object.keys(slice.actions);

      // All actions should start with capital 'L' for List
      actionNames.forEach((name) => {
        expect(name).toMatch(/^[a-z]+List/);
      });
    });
  });

  describe('Initial State', () => {
    it('should use provided initial filters', () => {
      const customInitial: GraphFilters = {
        timeWindow: '3h',
        searchTags: [{ text: 'test', mode: 'include' }],
        softwareOnly: true,
      };

      const slice = createFilterSlice('graph', customInitial);
      const state = slice.getInitialState();

      expect(state.filters).toEqual(customInitial);
    });
  });

  describe('Search Tag Actions', () => {
    it('should add search tag to undefined array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphSearchTag',
        payload: { text: 'engineer', mode: 'include' as const },
      });

      expect(newState.filters.searchTags).toHaveLength(1);
      expect(newState.filters.searchTags?.[0].text).toBe('engineer');
    });

    it('should add search tag to existing array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'frontend', mode: 'include' }],
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphSearchTag',
        payload: { text: 'backend', mode: 'include' as const },
      });

      expect(newState.filters.searchTags).toHaveLength(2);
      expect(newState.filters.searchTags?.map((t) => t.text)).toEqual(['frontend', 'backend']);
    });

    it('should remove search tag by text', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [
          { text: 'frontend', mode: 'include' },
          { text: 'backend', mode: 'include' },
        ],
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/removeGraphSearchTag',
        payload: 'frontend',
      });

      expect(newState.filters.searchTags).toHaveLength(1);
      expect(newState.filters.searchTags?.[0].text).toBe('backend');
    });

    it('should toggle search tag mode (include <-> exclude)', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'frontend', mode: 'include' }],
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/toggleGraphSearchTagMode',
        payload: 'frontend',
      });

      expect(newState.filters.searchTags?.[0].mode).toBe('exclude');
    });

    it('should clear all search tags (set to undefined)', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [
          { text: 'frontend', mode: 'include' },
          { text: 'backend', mode: 'include' },
        ],
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/clearGraphSearchTags',
        payload: undefined,
      });

      expect(newState.filters.searchTags).toBeUndefined();
    });
  });

  describe('Location Actions', () => {
    it('should add location to filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphLocation',
        payload: 'San Francisco, CA',
      });

      expect(newState.filters.location).toContain('San Francisco, CA');
    });

    it('should remove location from filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        location: ['San Francisco, CA', 'New York, NY'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/removeGraphLocation',
        payload: 'San Francisco, CA',
      });

      expect(newState.filters.location).toEqual(['New York, NY']);
    });

    it('should clear all locations', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        location: ['San Francisco, CA', 'New York, NY'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/clearGraphLocations',
        payload: undefined,
      });

      expect(newState.filters.location).toBeUndefined();
    });

    it('should set entire location array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphLocation',
        payload: ['Los Angeles, CA', 'Austin, TX'],
      });

      expect(newState.filters.location).toEqual(['Los Angeles, CA', 'Austin, TX']);
    });
  });

  describe('Department Actions', () => {
    it('should add department to filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/addGraphDepartment',
        payload: 'Engineering',
      });

      expect(newState.filters.department).toContain('Engineering');
    });

    it('should remove department from filters', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        department: ['Engineering', 'Design'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/removeGraphDepartment',
        payload: 'Engineering',
      });

      expect(newState.filters.department).toEqual(['Design']);
    });

    it('should clear all departments', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
        department: ['Engineering', 'Design'],
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/clearGraphDepartments',
        payload: undefined,
      });

      expect(newState.filters.department).toBeUndefined();
    });

    it('should set entire department array', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphDepartment',
        payload: ['Product', 'Sales'],
      });

      expect(newState.filters.department).toEqual(['Product', 'Sales']);
    });
  });

  describe('Software Only Actions', () => {
    it('should toggle software only (add/remove SE tags)', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/toggleGraphSoftwareOnly',
        payload: undefined,
      });

      // Software only should add SE tags
      expect(newState.filters.searchTags).toBeDefined();
      expect(newState.filters.searchTags!.length).toBeGreaterThan(0);
    });

    it('should set software only to true', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphSoftwareOnly',
        payload: true,
      });

      expect(newState.filters.searchTags).toBeDefined();
      expect(newState.filters.searchTags!.length).toBeGreaterThan(0);
    });

    it('should set software only to false', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [
          { text: 'software engineer', mode: 'include' },
          { text: 'developer', mode: 'include' },
        ],
        softwareOnly: true,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const initialState = { filters: initialFilters, hydrated: false, userModified: false };

      const newState = slice.reducer(initialState, {
        type: 'graphFilters/setGraphSoftwareOnly',
        payload: false,
      });

      // Should remove all SE tags, resulting in undefined
      expect(newState.filters.searchTags).toBeUndefined();
    });
  });

  describe('Edge Cases', () => {
    it('should preserve slice name after reset', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '7d',
        searchTags: [{ text: 'test', mode: 'include' }],
        softwareOnly: true,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const state = { filters: initialFilters, hydrated: false, userModified: false };

      slice.reducer(state, {
        type: 'graphFilters/resetGraphFilters',
        payload: undefined,
      });

      // Slice name should still be graphFilters
      expect(slice.name).toBe('graphFilters');
    });

    it('should work with Immer Draft types (Object.assign) on reset', () => {
      const initialFilters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const slice = createFilterSlice('graph', initialFilters);
      const modifiedState = {
        filters: {
          timeWindow: '7d' as TimeWindow,
          searchTags: [{ text: 'test', mode: 'include' as const }],
          softwareOnly: true,
        },
        hydrated: false,
        userModified: false,
      };

      // Reset uses Object.assign for Immer compatibility
      const newState = slice.reducer(modifiedState, {
        type: 'graphFilters/resetGraphFilters',
        payload: undefined,
      });

      // Should successfully assign all properties back to the initial values
      expect(newState.filters).toEqual(initialFilters);
    });
  });

  describe('userModified guard (saved-filters hydration race)', () => {
    const baseFilters: GraphFilters = {
      timeWindow: '7d',
      searchTags: undefined,
      softwareOnly: false,
    };
    const addRust = {
      type: 'graphFilters/addGraphSearchTag',
      payload: { text: 'rust', mode: 'include' as const },
    };
    const hydrate = {
      type: 'graphFilters/hydrateGraphFilters',
      payload: {
        timeWindow: '30d' as TimeWindow,
        searchTags: [{ text: 'golang', mode: 'include' as const }],
      },
    };

    it('starts un-modified and flips userModified on any user edit', () => {
      const slice = createFilterSlice('graph', baseFilters);
      expect(slice.getInitialState().userModified).toBe(false);

      const next = slice.reducer(slice.getInitialState(), addRust);
      expect(next.userModified).toBe(true);
    });

    it('hydrates normally when the slice is pristine', () => {
      const slice = createFilterSlice('graph', baseFilters);
      const next = slice.reducer(slice.getInitialState(), hydrate);

      expect(next.hydrated).toBe(true);
      expect(next.filters.timeWindow).toBe('30d');
      expect(next.filters.searchTags).toEqual([{ text: 'golang', mode: 'include' }]);
    });

    it('does NOT clobber a keyword the user added before a late hydration', () => {
      const slice = createFilterSlice('graph', baseFilters);

      // User adds a keyword while the saved-filters queries are still pending
      // (hydrated is still false — this is the cold-start window).
      let state = slice.reducer(slice.getInitialState(), addRust);
      expect(state.userModified).toBe(true);
      expect(state.hydrated).toBe(false);

      // Hydration finally lands with the saved default list.
      state = slice.reducer(state, hydrate);

      // The user's in-progress edit survives; the saved defaults are NOT applied
      // over it (this is the bug: a late hydration used to wipe "rust").
      expect(state.filters.searchTags).toEqual([{ text: 'rust', mode: 'include' }]);
      expect(state.filters.timeWindow).toBe('7d');
      // ...but hydration is marked done so the effect won't keep retrying.
      expect(state.hydrated).toBe(true);
    });

    it('reset clears userModified so the next sign-in can re-hydrate', () => {
      const slice = createFilterSlice('graph', baseFilters);

      let state = slice.reducer(slice.getInitialState(), addRust);
      expect(state.userModified).toBe(true);

      state = slice.reducer(state, {
        type: 'graphFilters/resetGraphFilters',
        payload: undefined,
      });
      expect(state.userModified).toBe(false);
      expect(state.filters).toEqual(baseFilters);

      // After reset, a hydration seeds defaults again (slice is pristine).
      state = slice.reducer(state, hydrate);
      expect(state.filters.searchTags).toEqual([{ text: 'golang', mode: 'include' }]);
    });
  });

  // The matcher and its `nonEditTypes` denylist are regenerated per
  // `createFilterSlice` call from name-derived action-type strings, so a
  // name-derivation bug (or a dropped non-edit type) would be slice-specific.
  // We therefore prove the same behavior directly for EVERY slice name the
  // factory supports — not just `graph` — by building each slice via the factory
  // (no store) and dispatching against a PRISTINE initial state.
  //
  // Per slice we assert:
  //   (a) its OWN edit actions flip `userModified` → true (including a
  //       no-op-guarded edit valid for that slice's filter shape), and
  //   (b) its OWN hydrate / setHydrated / reset actions do NOT flip
  //       `userModified` (the `!nonEditTypes.has(...)` exclusion branch). This is
  //       the one matcher branch with no other behavioral coverage and it guards
  //       the denylist-maintenance invariant documented on `extraReducers`.
  describe('userModified matcher — per-slice coverage', () => {
    function capitalize(s: string): string {
      return s.charAt(0).toUpperCase() + s.slice(1);
    }

    type SliceCase = {
      name: FilterSliceName;
      // Build the slice's initial filters with the correct shape for this name.
      makeSlice: () => ReturnType<typeof createFilterSlice>;
      // Two representative EDIT actions, including a no-op-guarded one
      // (add{Name}Department for graph/list; add{Name}Company for recentJobs).
      editActions: { type: string; payload: unknown }[];
    };

    const graphInitial: GraphFilters = {
      timeWindow: '7d',
      searchTags: undefined,
      softwareOnly: false,
    };
    const listInitial: ListFilters = {
      timeWindow: '7d',
      searchTags: undefined,
      softwareOnly: false,
    };
    const recentJobsInitial: RecentJobsFilters = {
      timeWindow: '3h',
      searchTags: undefined,
      softwareOnly: false,
      company: undefined,
    };

    const cases: SliceCase[] = [
      {
        name: 'graph',
        makeSlice: () => createFilterSlice('graph', graphInitial),
        editActions: [
          { type: 'graphFilters/setGraphTimeWindow', payload: '30d' as TimeWindow },
          // No-op-guarded edit: graph owns `department`, so this mutates.
          { type: 'graphFilters/addGraphDepartment', payload: 'Engineering' },
        ],
      },
      {
        name: 'list',
        makeSlice: () => createFilterSlice('list', listInitial),
        editActions: [
          { type: 'listFilters/setListTimeWindow', payload: '30d' as TimeWindow },
          // No-op-guarded edit: list owns `department`, so this mutates.
          { type: 'listFilters/addListDepartment', payload: 'Engineering' },
        ],
      },
      {
        name: 'recentJobs',
        makeSlice: () => createFilterSlice('recentJobs', recentJobsInitial),
        editActions: [
          { type: 'recentJobsFilters/setRecentJobsTimeWindow', payload: '24h' as TimeWindow },
          // recentJobs has no `department`; it owns `company` instead. This is
          // the no-op-guarded edit for this slice shape.
          { type: 'recentJobsFilters/addRecentJobsCompany', payload: 'netflix' },
        ],
      },
    ];

    describe.each(cases)('$name slice', ({ name, makeSlice, editActions }) => {
      const cap = capitalize(name);
      const prefix = `${name}Filters/`;

      it('starts un-modified', () => {
        expect(makeSlice().getInitialState().userModified).toBe(false);
      });

      it.each(editActions)('flips userModified=true on edit $type', (action) => {
        const slice = makeSlice();
        const next = slice.reducer(slice.getInitialState(), action);
        expect(next.userModified).toBe(true);
      });

      it(`does NOT flip userModified on hydrate${cap}Filters (and still hydrates)`, () => {
        const slice = makeSlice();
        const next = slice.reducer(slice.getInitialState(), {
          type: `${prefix}hydrate${cap}Filters`,
          payload: { timeWindow: '30d' as TimeWindow },
        });
        expect(next.userModified).toBe(false);
        // Pristine slice → seeding is applied and the slice is marked hydrated.
        expect(next.hydrated).toBe(true);
        expect(next.filters.timeWindow).toBe('30d');
      });

      it(`does NOT flip userModified on set${cap}Hydrated(true)`, () => {
        const slice = makeSlice();
        const next = slice.reducer(slice.getInitialState(), {
          type: `${prefix}set${cap}Hydrated`,
          payload: true,
        });
        expect(next.userModified).toBe(false);
        expect(next.hydrated).toBe(true);
      });

      it(`does NOT flip userModified on reset${cap}Filters`, () => {
        const slice = makeSlice();
        const next = slice.reducer(slice.getInitialState(), {
          type: `${prefix}reset${cap}Filters`,
          payload: undefined,
        });
        expect(next.userModified).toBe(false);
      });
    });
  });
});
