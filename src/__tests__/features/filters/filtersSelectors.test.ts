import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  selectGraphFilteredJobs,
  selectListFilteredJobs,
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../../features/filters/filtersSelectors';
import type { RootState } from '../../../app/store';
import type { Job } from '../../../types';

describe('filtersSelectors', () => {
  // Mock current time for consistent time window testing
  beforeEach(() => {
    vi.setSystemTime(new Date('2025-11-20T12:00:00Z'));
  });

  const createMockJob = (overrides: Partial<Job>): Job => ({
    id: '1',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Software Engineer',
    department: 'Engineering',
    location: 'Los Angeles',
    createdAt: '2025-11-20T11:00:00Z',
    url: 'https://example.com/job/1',
    classification: {
      isSoftwareAdjacent: true,
      category: 'fullstack',
      confidence: 0.9,
      matchedKeywords: ['software engineer'],
    },
    raw: {},
    ...overrides,
  });

  const softwareJob = createMockJob({
    id: '1',
    title: 'Frontend Engineer',
    department: 'Engineering',
    location: 'Los Angeles, CA',
    createdAt: '2025-11-20T11:00:00Z', // 1 hour ago
    classification: {
      isSoftwareAdjacent: true,
      category: 'frontend',
      confidence: 0.9,
      matchedKeywords: ['frontend'],
    },
  });

  const nonTechJob = createMockJob({
    id: '2',
    title: 'HR Manager',
    department: 'Human Resources',
    location: 'New York, NY',
    createdAt: '2025-11-20T10:00:00Z', // 2 hours ago
    classification: {
      isSoftwareAdjacent: false,
      category: 'nonTech',
      confidence: 0.9,
      matchedKeywords: [],
    },
  });

  const oldJob = createMockJob({
    id: '3',
    title: 'Backend Engineer',
    department: 'Engineering',
    location: 'Los Angeles, CA',
    createdAt: '2025-11-18T12:00:00Z', // 2 days ago
    classification: {
      isSoftwareAdjacent: true,
      category: 'backend',
      confidence: 0.9,
      matchedKeywords: ['backend'],
    },
  });

  const createMockState = (jobs: Job[], graphFilters = {}, listFilters = {}): RootState => ({
    app: {
      selectedCompanyId: 'spacex',
      selectedView: 'greenhouse',
      isInitialized: true,
    },
    jobs: {
      byCompany: {
        spacex: {
          items: jobs,
          isLoading: false,
          metadata: {
            totalCount: jobs.length,
            softwareCount: jobs.filter(j => j.classification.isSoftwareAdjacent).length,
          },
        },
      },
    },
    filters: {
      graph: {
        timeWindow: '24h',
        softwareOnly: true,
        roleCategory: 'all',
        ...graphFilters,
      },
      list: {
        timeWindow: '24h',
        searchQuery: undefined,
        softwareOnly: true,
        roleCategory: 'all',
        ...listFilters,
      },
    },
    ui: {
      graphModal: { open: false },
      globalLoading: false,
      notifications: [],
    },
  });

  describe('selectGraphFilteredJobs', () => {
    it('should filter by time window', () => {
      const state = createMockState([softwareJob, oldJob], { timeWindow: '1h' });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(1);
      expect(filtered[0].id).toBe('1');
    });

    it('should filter by search query', () => {
      const state = createMockState([softwareJob, nonTechJob, oldJob], {
        searchQuery: ['frontend'],
        softwareOnly: false,
        timeWindow: '3d'
      });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(1);
      expect(filtered[0].title).toContain('Frontend');
    });

    it('should filter by multiple search tags with OR logic', () => {
      const state = createMockState([softwareJob, nonTechJob, oldJob], {
        searchQuery: ['frontend', 'hr'],
        softwareOnly: false,
        timeWindow: '3d'
      });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(2); // Frontend job + HR job
      expect(filtered.some(j => j.title.includes('Frontend'))).toBe(true);
      expect(filtered.some(j => j.title.includes('HR'))).toBe(true);
    });

    it('should handle substring matching in graph search', () => {
      const state = createMockState([softwareJob], {
        searchQuery: ['front'],
        timeWindow: '3d'
      });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(1);
    });

    it('should be case insensitive in graph search', () => {
      const state = createMockState([softwareJob], {
        searchQuery: ['FRONTEND'],
        timeWindow: '3d'
      });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(1);
    });

    it('should filter out non-software jobs when softwareOnly is true', () => {
      const state = createMockState([softwareJob, nonTechJob], { softwareOnly: true });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(1);
      expect(filtered[0].classification.isSoftwareAdjacent).toBe(true);
    });

    it('should include non-software jobs when softwareOnly is false', () => {
      const state = createMockState([softwareJob, nonTechJob], { softwareOnly: false });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(2);
    });

    it('should filter by location', () => {
      const state = createMockState([softwareJob, nonTechJob], {
        location: ['Los Angeles, CA'],
        softwareOnly: false
      });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(1);
      expect(filtered[0].location).toBe('Los Angeles, CA');
    });

    it('should filter by role category', () => {
      const state = createMockState([softwareJob, oldJob], {
        roleCategory: 'frontend',
        timeWindow: '3d'
      });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(1);
      expect(filtered[0].classification.category).toBe('frontend');
    });

    it('should filter by multiple locations with OR logic', () => {
      const state = createMockState([softwareJob, nonTechJob], {
        location: ['Los Angeles, CA', 'New York, NY'],
        softwareOnly: false
      });
      const filtered = selectGraphFilteredJobs(state);

      expect(filtered).toHaveLength(2);
    });

    it('should filter by "United States" meta-filter', () => {
      const remoteJob = createMockJob({
        id: '4',
        title: 'Remote Engineer',
        location: 'Remote',
        createdAt: '2025-11-20T11:30:00Z',
      });

      const state = createMockState([softwareJob, nonTechJob, remoteJob], {
        location: ['United States'],
        softwareOnly: false
      });
      const filtered = selectGraphFilteredJobs(state);

      // Should match LA (has CA state code), NY (has state code), and Remote
      expect(filtered).toHaveLength(3);
    });
  });

  describe('selectListFilteredJobs', () => {
    it('should filter by search query', () => {
      const state = createMockState([softwareJob, nonTechJob, oldJob], {}, {
        searchQuery: ['frontend'],
        softwareOnly: false,
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(1);
      expect(filtered[0].title).toContain('Frontend');
    });

    it('should filter by multiple search tags with OR logic', () => {
      const state = createMockState([softwareJob, nonTechJob, oldJob], {}, {
        searchQuery: ['frontend', 'hr'],
        softwareOnly: false,
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(2); // Frontend job + HR job
      expect(filtered.some(j => j.title.includes('Frontend'))).toBe(true);
      expect(filtered.some(j => j.title.includes('HR'))).toBe(true);
    });

    it('should return all jobs when no tags match', () => {
      const state = createMockState([softwareJob, nonTechJob], {}, {
        searchQuery: ['nonexistent'],
        softwareOnly: false,
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(0);
    });

    it('should search across multiple fields', () => {
      const jobWithTag = createMockJob({
        id: '4',
        title: 'Software Engineer',
        tags: ['react', 'javascript'],
        createdAt: '2025-11-20T11:30:00Z',
      });

      const state = createMockState([jobWithTag], {}, {
        searchQuery: ['react'],
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(1);
    });

    it('should be case insensitive', () => {
      const state = createMockState([softwareJob], {}, {
        searchQuery: ['FRONTEND'],
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(1);
    });

    it('should handle substring matching', () => {
      const state = createMockState([softwareJob], {}, {
        searchQuery: ['front'],
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(1);
    });

    it('should return all jobs when searchQuery is undefined', () => {
      const state = createMockState([softwareJob, oldJob], {}, {
        searchQuery: undefined,
        softwareOnly: false,
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(2);
    });

    it('should return all jobs when searchQuery is empty array', () => {
      const state = createMockState([softwareJob, oldJob], {}, {
        searchQuery: [],
        softwareOnly: false,
        timeWindow: '3d'
      });
      const filtered = selectListFilteredJobs(state);

      expect(filtered).toHaveLength(2);
    });
  });

  describe('selectAvailableLocations', () => {
    it('should return unique locations with "United States" first', () => {
      const state = createMockState([softwareJob, nonTechJob, oldJob]);
      const locations = selectAvailableLocations(state);

      expect(locations).toEqual(['United States', 'Los Angeles, CA', 'New York, NY']);
    });

    it('should filter out undefined locations', () => {
      const jobWithoutLocation = createMockJob({ id: '4', location: undefined });
      const state = createMockState([softwareJob, jobWithoutLocation]);
      const locations = selectAvailableLocations(state);

      expect(locations).toEqual(['United States', 'Los Angeles, CA']);
    });
  });

  describe('selectAvailableDepartments', () => {
    it('should return unique departments', () => {
      const state = createMockState([softwareJob, nonTechJob, oldJob]);
      const departments = selectAvailableDepartments(state);

      expect(departments).toEqual(['Engineering', 'Human Resources']);
    });
  });
});
