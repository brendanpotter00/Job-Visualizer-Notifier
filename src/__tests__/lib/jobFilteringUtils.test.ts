import { describe, it, expect, beforeEach } from 'vitest';
import type { Job, GraphFilters, SearchTag } from '../../types';
import {
  isJobWithinTimeWindow,
  matchesSearchTags,
  matchesLocation,
  matchesDepartment,
  matchesEmploymentType,
  filterJobsByFilters,
} from '../../features/filters/utils/jobFilteringUtils';

// Helper to create mock jobs
const createMockJob = (overrides: Partial<Job> = {}): Job => ({
  id: '1',
  source: 'greenhouse',
  company: 'test-company',
  title: 'Software Engineer',
  department: 'Engineering',
  team: 'Backend',
  location: 'San Francisco',
  employmentType: 'Full-time',
  createdAt: new Date().toISOString(),
  url: 'https://example.com/job/1',
  raw: {},
  ...overrides,
});

describe('jobFilteringUtils', () => {
  describe('isJobWithinTimeWindow', () => {
    it('should return true for jobs within 30 days window', () => {
      const job = createMockJob({
        createdAt: new Date(Date.now() - 15 * 24 * 60 * 60 * 1000).toISOString(), // 15 days ago
      });

      expect(isJobWithinTimeWindow(job.createdAt, '30d')).toBe(true);
    });

    it('should return false for jobs outside 30 days window', () => {
      const job = createMockJob({
        createdAt: new Date(Date.now() - 31 * 24 * 60 * 60 * 1000).toISOString(), // 31 days ago
      });

      expect(isJobWithinTimeWindow(job.createdAt, '30d')).toBe(false);
    });

    it('should return true for jobs within 7 days window', () => {
      const job = createMockJob({
        createdAt: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), // 3 days ago
      });

      expect(isJobWithinTimeWindow(job.createdAt, '7d')).toBe(true);
    });

    it('should return false for jobs outside 7 days window', () => {
      const job = createMockJob({
        createdAt: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(), // 8 days ago
      });

      expect(isJobWithinTimeWindow(job.createdAt, '7d')).toBe(false);
    });

    it('should handle 24h time window', () => {
      const recentJob = createMockJob({
        createdAt: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(), // 12 hours ago
      });
      const oldJob = createMockJob({
        createdAt: new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(), // 25 hours ago
      });

      expect(isJobWithinTimeWindow(recentJob.createdAt, '24h')).toBe(true);
      expect(isJobWithinTimeWindow(oldJob.createdAt, '24h')).toBe(false);
    });
  });

  describe('matchesSearchTags', () => {
    it('should return true when no search tags are provided', () => {
      const job = createMockJob();

      expect(matchesSearchTags(job, undefined)).toBe(true);
      expect(matchesSearchTags(job, [])).toBe(true);
    });

    it('should match include tags (OR logic)', () => {
      const job = createMockJob({ title: 'Senior Software Engineer' });
      const tags: SearchTag[] = [{ text: 'software', mode: 'include' }];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should match include tags in department', () => {
      const job = createMockJob({ department: 'Engineering' });
      const tags: SearchTag[] = [{ text: 'engineering', mode: 'include' }];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should match include tags in location', () => {
      const job = createMockJob({ location: 'San Francisco' });
      const tags: SearchTag[] = [{ text: 'francisco', mode: 'include' }];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should match include tags in team', () => {
      const job = createMockJob({ team: 'Backend' });
      const tags: SearchTag[] = [{ text: 'backend', mode: 'include' }];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should match include tags in job tags array', () => {
      const job = createMockJob({ tags: ['remote', 'senior'] });
      const tags: SearchTag[] = [{ text: 'remote', mode: 'include' }];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should match any include tag (OR logic)', () => {
      const job = createMockJob({ title: 'Frontend Developer' });
      const tags: SearchTag[] = [
        { text: 'backend', mode: 'include' },
        { text: 'frontend', mode: 'include' },
      ];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should fail when no include tags match', () => {
      const job = createMockJob({ title: 'Data Scientist' });
      const tags: SearchTag[] = [{ text: 'software', mode: 'include' }];

      expect(matchesSearchTags(job, tags)).toBe(false);
    });

    it('should filter out jobs matching exclude tags', () => {
      const job = createMockJob({ title: 'Product Manager' });
      const tags: SearchTag[] = [{ text: 'manager', mode: 'exclude' }];

      expect(matchesSearchTags(job, tags)).toBe(false);
    });

    it('should pass when no exclude tags match', () => {
      const job = createMockJob({ title: 'Software Engineer' });
      const tags: SearchTag[] = [{ text: 'manager', mode: 'exclude' }];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should handle combination of include and exclude tags', () => {
      const job = createMockJob({ title: 'Senior Software Engineer' });
      const tags: SearchTag[] = [
        { text: 'software', mode: 'include' },
        { text: 'manager', mode: 'exclude' },
      ];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });

    it('should fail when include matches but exclude also matches', () => {
      const job = createMockJob({ title: 'Software Engineering Manager' });
      const tags: SearchTag[] = [
        { text: 'software', mode: 'include' },
        { text: 'manager', mode: 'exclude' },
      ];

      expect(matchesSearchTags(job, tags)).toBe(false);
    });

    it('should be case insensitive', () => {
      const job = createMockJob({ title: 'SOFTWARE ENGINEER' });
      const tags: SearchTag[] = [{ text: 'software', mode: 'include' }];

      expect(matchesSearchTags(job, tags)).toBe(true);
    });
  });

  describe('matchesLocation', () => {
    it('should return true when no location filter provided', () => {
      const job = createMockJob();

      expect(matchesLocation(job, undefined)).toBe(true);
      expect(matchesLocation(job, [])).toBe(true);
    });

    it('should match exact location', () => {
      const job = createMockJob({ location: 'San Francisco' });

      expect(matchesLocation(job, ['San Francisco'])).toBe(true);
    });

    it('should match any location (OR logic)', () => {
      const job = createMockJob({ location: 'New York' });

      expect(matchesLocation(job, ['San Francisco', 'New York'])).toBe(true);
    });

    it('should fail when location does not match', () => {
      const job = createMockJob({ location: 'Austin' });

      expect(matchesLocation(job, ['San Francisco', 'New York'])).toBe(false);
    });

    it('should handle "United States" meta-filter for US locations', () => {
      const jobInCalifornia = createMockJob({ location: 'San Francisco, CA' });
      const jobInTexas = createMockJob({ location: 'Austin, TX' });
      const jobInUK = createMockJob({ location: 'London, UK' });

      expect(matchesLocation(jobInCalifornia, ['United States'])).toBe(true);
      expect(matchesLocation(jobInTexas, ['United States'])).toBe(true);
      expect(matchesLocation(jobInUK, ['United States'])).toBe(false);
    });

    it('should handle combination of specific location and United States', () => {
      const job = createMockJob({ location: 'London, UK' });

      expect(matchesLocation(job, ['United States', 'London, UK'])).toBe(true);
    });
  });

  describe('matchesDepartment', () => {
    it('should return true when no department filter provided', () => {
      const job = createMockJob();

      expect(matchesDepartment(job, undefined)).toBe(true);
      expect(matchesDepartment(job, [])).toBe(true);
    });

    it('should match exact department', () => {
      const job = createMockJob({ department: 'Engineering' });

      expect(matchesDepartment(job, ['Engineering'])).toBe(true);
    });

    it('should match any department (OR logic)', () => {
      const job = createMockJob({ department: 'Product' });

      expect(matchesDepartment(job, ['Engineering', 'Product'])).toBe(true);
    });

    it('should fail when department does not match', () => {
      const job = createMockJob({ department: 'Sales' });

      expect(matchesDepartment(job, ['Engineering', 'Product'])).toBe(false);
    });
  });

  describe('matchesEmploymentType', () => {
    it('should return true when no employment type filter provided', () => {
      const job = createMockJob();

      expect(matchesEmploymentType(job, undefined)).toBe(true);
    });

    it('should match employment type', () => {
      const job = createMockJob({ employmentType: 'Full-time' });

      expect(matchesEmploymentType(job, 'Full-time')).toBe(true);
    });

    it('should fail when employment type does not match', () => {
      const job = createMockJob({ employmentType: 'Full-time' });

      expect(matchesEmploymentType(job, 'Part-time')).toBe(false);
    });
  });

  describe('filterJobsByFilters', () => {
    let jobs: Job[];

    beforeEach(() => {
      const now = Date.now();
      jobs = [
        createMockJob({
          id: '1',
          title: 'Senior Software Engineer',
          department: 'Engineering',
          location: 'San Francisco',
          employmentType: 'Full-time',
          createdAt: new Date(now - 5 * 24 * 60 * 60 * 1000).toISOString(), // 5 days ago
        }),
        createMockJob({
          id: '2',
          title: 'Frontend Developer',
          department: 'Engineering',
          location: 'New York',
          employmentType: 'Full-time',
          createdAt: new Date(now - 10 * 24 * 60 * 60 * 1000).toISOString(), // 10 days ago
        }),
        createMockJob({
          id: '3',
          title: 'Product Manager',
          department: 'Product',
          location: 'Remote',
          employmentType: 'Full-time',
          createdAt: new Date(now - 2 * 24 * 60 * 60 * 1000).toISOString(), // 2 days ago
        }),
        createMockJob({
          id: '4',
          title: 'Data Engineer',
          department: 'Data',
          location: 'Austin, TX',
          employmentType: 'Contract',
          createdAt: new Date(now - 40 * 24 * 60 * 60 * 1000).toISOString(), // 40 days ago
        }),
      ];
    });

    it('should filter by time window', () => {
      const filters: GraphFilters = {
        timeWindow: '7d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      expect(result).toHaveLength(2); // Jobs 1 and 3 within 7 days
      expect(result.map((j) => j.id)).toContain('1');
      expect(result.map((j) => j.id)).toContain('3');
    });

    it('should filter by search tags (include)', () => {
      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'software', mode: 'include' }],
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      expect(result).toHaveLength(1); // Only job 1
      expect(result[0].id).toBe('1');
    });

    it('should filter by search tags (exclude)', () => {
      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'manager', mode: 'exclude' }],
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      expect(result).toHaveLength(2); // Jobs 1 and 2 (not 3)
      expect(result.map((j) => j.id)).not.toContain('3');
    });

    it('should filter by location', () => {
      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        location: ['San Francisco'],
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('1');
    });

    it('should filter by department', () => {
      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        department: ['Engineering'],
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      expect(result).toHaveLength(2); // Jobs 1 and 2
      expect(result.map((j) => j.id).sort()).toEqual(['1', '2']);
    });

    it('should filter by employment type', () => {
      // Note: Job 4 is 40 days old, so use 30d window which will filter it out by time
      // Need to adjust the test data - let's use a closer time range job
      const recentContractJob = createMockJob({
        id: '5',
        title: 'Contract Developer',
        employmentType: 'Contract',
        createdAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(), // 5 days ago
      });
      const testJobs = [...jobs, recentContractJob];

      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        employmentType: 'Contract',
        softwareOnly: false,
      };

      const result = filterJobsByFilters(testJobs, filters);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('5');
    });

    it('should combine multiple filters (AND logic)', () => {
      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'engineer', mode: 'include' }],
        department: ['Engineering'],
        location: ['San Francisco'],
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('1');
    });

    it('should return all jobs when no filters applied within time window', () => {
      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: undefined,
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      // Only jobs 1, 2, and 3 are within 30 days (job 4 is 40 days old)
      expect(result).toHaveLength(3);
    });

    it('should return empty array when no jobs match filters', () => {
      const filters: GraphFilters = {
        timeWindow: '30d',
        searchTags: [{ text: 'nonexistent', mode: 'include' }],
        softwareOnly: false,
      };

      const result = filterJobsByFilters(jobs, filters);

      expect(result).toHaveLength(0);
    });
  });
});
