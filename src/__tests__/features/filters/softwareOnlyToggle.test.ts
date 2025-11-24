import { describe, it, expect } from 'vitest';
import graphFiltersReducer, {
  toggleGraphSoftwareOnly,
  setGraphSoftwareOnly,
  type GraphFiltersState,
} from '../../../features/filters/graphFiltersSlice';
import listFiltersReducer, {
  toggleListSoftwareOnly,
  type ListFiltersState,
} from '../../../features/filters/listFiltersSlice';
import { selectGraphSoftwareOnlyState } from '../../../features/filters/graphFiltersSelectors';
import { selectListSoftwareOnlyState } from '../../../features/filters/listFiltersSelectors';
import type { RootState } from '../../../app/store';
import { SOFTWARE_ENGINEERING_TAGS } from '../../../constants/softwareEngineeringTags';
import type { SearchTag } from '../../../types';

// Helper to create a minimal RootState for selector testing
function createMockState(searchTags?: SearchTag[]): RootState {
  return {
    graphFilters: {
      filters: {
        timeWindow: '30d',
        searchTags,
        softwareOnly: false,
      },
    },
    listFilters: {
      filters: {
        timeWindow: '30d',
        searchTags,
        softwareOnly: false,
      },
    },
  } as RootState;
}

describe('Software Engineering Toggle - Graph Filters', () => {
  const initialState: GraphFiltersState = {
    filters: {
      timeWindow: '30d',
      searchTags: undefined,
      softwareOnly: false,
    },
  };

  describe('toggleGraphSoftwareOnly', () => {
    it('should add all 6 software engineering tags when toggled ON', () => {
      const newState = graphFiltersReducer(initialState, toggleGraphSoftwareOnly());

      expect(newState.filters.searchTags).toHaveLength(6);
      expect(newState.filters.searchTags).toEqual([...SOFTWARE_ENGINEERING_TAGS]);
      expect(newState.filters.softwareOnly).toBe(true);
    });

    it('should remove all 6 software engineering tags when toggled OFF', () => {
      const stateWithTags: GraphFiltersState = {
        filters: {
          timeWindow: '30d',
          searchTags: [...SOFTWARE_ENGINEERING_TAGS],
          softwareOnly: true,
        },
      };

      const newState = graphFiltersReducer(stateWithTags, toggleGraphSoftwareOnly());

      expect(newState.filters.searchTags).toBeUndefined();
      expect(newState.filters.softwareOnly).toBe(false);
    });

    it('should preserve non-SE tags when toggling OFF (smart removal)', () => {
      const customTag: SearchTag = { text: 'python', mode: 'include' };
      const stateWithMixedTags: GraphFiltersState = {
        filters: {
          timeWindow: '30d',
          searchTags: [...SOFTWARE_ENGINEERING_TAGS, customTag],
          softwareOnly: true,
        },
      };

      const newState = graphFiltersReducer(stateWithMixedTags, toggleGraphSoftwareOnly());

      expect(newState.filters.searchTags).toEqual([customTag]);
      expect(newState.filters.softwareOnly).toBe(false);
    });

    it('should not add duplicate tags if some SE tags already exist', () => {
      const stateWithSomeTags: GraphFiltersState = {
        filters: {
          timeWindow: '30d',
          searchTags: [
            { text: 'developer', mode: 'include' },
            { text: 'python', mode: 'include' },
          ],
          softwareOnly: false,
        },
      };

      const newState = graphFiltersReducer(stateWithSomeTags, toggleGraphSoftwareOnly());

      // Should add the 5 missing SE tags, not duplicate 'developer'
      expect(newState.filters.searchTags).toHaveLength(7); // 2 original + 5 new SE tags
      expect(newState.filters.searchTags?.filter((t) => t.text === 'developer')).toHaveLength(1);
      expect(newState.filters.softwareOnly).toBe(true);
    });

    it('should handle toggle ON when some non-SE tags exist', () => {
      const customTag: SearchTag = { text: 'react', mode: 'include' };
      const stateWithCustomTag: GraphFiltersState = {
        filters: {
          timeWindow: '30d',
          searchTags: [customTag],
          softwareOnly: false,
        },
      };

      const newState = graphFiltersReducer(stateWithCustomTag, toggleGraphSoftwareOnly());

      expect(newState.filters.searchTags).toHaveLength(7); // 1 custom + 6 SE tags
      expect(newState.filters.searchTags).toContainEqual(customTag);
      expect(newState.filters.softwareOnly).toBe(true);
    });
  });

  describe('setGraphSoftwareOnly', () => {
    it('should add all SE tags when set to true', () => {
      const newState = graphFiltersReducer(initialState, setGraphSoftwareOnly(true));

      expect(newState.filters.searchTags).toHaveLength(6);
      expect(newState.filters.softwareOnly).toBe(true);
    });

    it('should remove all SE tags when set to false', () => {
      const stateWithTags: GraphFiltersState = {
        filters: {
          timeWindow: '30d',
          searchTags: [...SOFTWARE_ENGINEERING_TAGS],
          softwareOnly: true,
        },
      };

      const newState = graphFiltersReducer(stateWithTags, setGraphSoftwareOnly(false));

      expect(newState.filters.searchTags).toBeUndefined();
      expect(newState.filters.softwareOnly).toBe(false);
    });
  });

  describe('selectGraphSoftwareOnlyState', () => {
    it('should return true when all 6 SE tags are present', () => {
      const state = createMockState([...SOFTWARE_ENGINEERING_TAGS]);
      const isOn = selectGraphSoftwareOnlyState(state);

      expect(isOn).toBe(true);
    });

    it('should return false when no tags are present', () => {
      const state = createMockState(undefined);
      const isOn = selectGraphSoftwareOnlyState(state);

      expect(isOn).toBe(false);
    });

    it('should return false when only some SE tags are present', () => {
      const state = createMockState([
        { text: 'developer', mode: 'include' },
        { text: 'engineer', mode: 'include' },
      ]);
      const isOn = selectGraphSoftwareOnlyState(state);

      expect(isOn).toBe(false);
    });

    it('should return false when SE tag has wrong mode (exclude instead of include)', () => {
      const tagsWithWrongMode = SOFTWARE_ENGINEERING_TAGS.map((tag, idx) =>
        idx === 0 ? { ...tag, mode: 'exclude' as const } : tag
      );
      const state = createMockState([...tagsWithWrongMode]);
      const isOn = selectGraphSoftwareOnlyState(state);

      expect(isOn).toBe(false);
    });

    it('should return true even when non-SE tags are also present', () => {
      const state = createMockState([
        ...SOFTWARE_ENGINEERING_TAGS,
        { text: 'python', mode: 'include' },
        { text: 'remote', mode: 'include' },
      ]);
      const isOn = selectGraphSoftwareOnlyState(state);

      expect(isOn).toBe(true);
    });
  });
});

describe('Software Engineering Toggle - List Filters', () => {
  const initialState: ListFiltersState = {
    filters: {
      timeWindow: '30d',
      searchTags: undefined,
      softwareOnly: false,
    },
  };

  describe('toggleListSoftwareOnly', () => {
    it('should add all 6 software engineering tags when toggled ON', () => {
      const newState = listFiltersReducer(initialState, toggleListSoftwareOnly());

      expect(newState.filters.searchTags).toHaveLength(6);
      expect(newState.filters.searchTags).toEqual([...SOFTWARE_ENGINEERING_TAGS]);
      expect(newState.filters.softwareOnly).toBe(true);
    });

    it('should remove all 6 software engineering tags when toggled OFF', () => {
      const stateWithTags: ListFiltersState = {
        filters: {
          timeWindow: '30d',
          searchTags: [...SOFTWARE_ENGINEERING_TAGS],
          softwareOnly: true,
        },
      };

      const newState = listFiltersReducer(stateWithTags, toggleListSoftwareOnly());

      expect(newState.filters.searchTags).toBeUndefined();
      expect(newState.filters.softwareOnly).toBe(false);
    });

    it('should preserve non-SE tags when toggling OFF (smart removal)', () => {
      const customTag: SearchTag = { text: 'python', mode: 'include' };
      const stateWithMixedTags: ListFiltersState = {
        filters: {
          timeWindow: '30d',
          searchTags: [...SOFTWARE_ENGINEERING_TAGS, customTag],
          softwareOnly: true,
        },
      };

      const newState = listFiltersReducer(stateWithMixedTags, toggleListSoftwareOnly());

      expect(newState.filters.searchTags).toEqual([customTag]);
      expect(newState.filters.softwareOnly).toBe(false);
    });
  });

  describe('selectListSoftwareOnlyState', () => {
    it('should return true when all 6 SE tags are present', () => {
      const state = createMockState([...SOFTWARE_ENGINEERING_TAGS]);
      const isOn = selectListSoftwareOnlyState(state);

      expect(isOn).toBe(true);
    });

    it('should return false when only some SE tags are present', () => {
      const state = createMockState([
        { text: 'developer', mode: 'include' },
        { text: 'frontend', mode: 'include' },
      ]);
      const isOn = selectListSoftwareOnlyState(state);

      expect(isOn).toBe(false);
    });
  });
});

describe('Graph and List Independence', () => {
  it('should toggle graph filters without affecting list filters', () => {
    const graphState: GraphFiltersState = {
      filters: {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      },
    };

    const listState: ListFiltersState = {
      filters: {
        timeWindow: '30d',
        searchTags: [{ text: 'custom', mode: 'include' }],
        softwareOnly: false,
      },
    };

    // Toggle graph ON
    const newGraphState = graphFiltersReducer(graphState, toggleGraphSoftwareOnly());

    // List state should remain unchanged
    expect(newGraphState.filters.searchTags).toHaveLength(6);
    expect(listState.filters.searchTags).toHaveLength(1);
    expect(listState.filters.searchTags?.[0].text).toBe('custom');
  });

  it('should toggle list filters without affecting graph filters', () => {
    const graphState: GraphFiltersState = {
      filters: {
        timeWindow: '30d',
        searchTags: [...SOFTWARE_ENGINEERING_TAGS],
        softwareOnly: true,
      },
    };

    const listState: ListFiltersState = {
      filters: {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      },
    };

    // Toggle list ON
    const newListState = listFiltersReducer(listState, toggleListSoftwareOnly());

    // Graph state should remain unchanged
    expect(newListState.filters.searchTags).toHaveLength(6);
    expect(graphState.filters.searchTags).toHaveLength(6);
  });
});

describe('Integration with manual tag removal', () => {
  it('should auto-disable toggle when user manually removes an SE tag (graph)', () => {
    // Start with toggle ON (all SE tags present)
    const state = createMockState([...SOFTWARE_ENGINEERING_TAGS]);
    expect(selectGraphSoftwareOnlyState(state)).toBe(true);

    // User manually removes one SE tag
    const stateAfterRemoval = createMockState(
      SOFTWARE_ENGINEERING_TAGS.filter((tag) => tag.text !== 'developer')
    );

    // Toggle should now be OFF
    expect(selectGraphSoftwareOnlyState(stateAfterRemoval)).toBe(false);
  });

  it('should auto-disable toggle when user manually removes an SE tag (list)', () => {
    // Start with toggle ON (all SE tags present)
    const state = createMockState([...SOFTWARE_ENGINEERING_TAGS]);
    expect(selectListSoftwareOnlyState(state)).toBe(true);

    // User manually removes one SE tag
    const stateAfterRemoval = createMockState(
      SOFTWARE_ENGINEERING_TAGS.filter((tag) => tag.text !== 'frontend')
    );

    // Toggle should now be OFF
    expect(selectListSoftwareOnlyState(stateAfterRemoval)).toBe(false);
  });

  it('should handle toggle correctly after user toggles mode of an SE tag', () => {
    const tagsWithChangedMode = SOFTWARE_ENGINEERING_TAGS.map((tag, idx) =>
      idx === 0 ? { ...tag, mode: 'exclude' as const } : tag
    );

    const state = createMockState([...tagsWithChangedMode]);

    // Toggle should be OFF because one tag has wrong mode
    expect(selectGraphSoftwareOnlyState(state)).toBe(false);
  });
});

describe('Edge cases', () => {
  it('should handle empty tag array correctly', () => {
    const state = createMockState([]);
    expect(selectGraphSoftwareOnlyState(state)).toBe(false);
    expect(selectListSoftwareOnlyState(state)).toBe(false);
  });

  it('should handle toggle when tags array is undefined', () => {
    const initialState: GraphFiltersState = {
      filters: {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      },
    };

    const newState = graphFiltersReducer(initialState, toggleGraphSoftwareOnly());

    expect(newState.filters.searchTags).toBeDefined();
    expect(newState.filters.searchTags).toHaveLength(6);
  });

  it('should set searchTags to undefined when removing all SE tags and no other tags exist', () => {
    const initialState: GraphFiltersState = {
      filters: {
        timeWindow: '30d',
        searchTags: [...SOFTWARE_ENGINEERING_TAGS],
        softwareOnly: true,
      },
    };

    const newState = graphFiltersReducer(initialState, toggleGraphSoftwareOnly());

    expect(newState.filters.searchTags).toBeUndefined();
  });
});
