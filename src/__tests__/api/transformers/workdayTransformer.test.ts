import { describe, it, expect } from 'vitest';
import { transformWorkdayJob } from '../../../api/transformers/workdayTransformer';
import type { WorkdayJobPosting } from '../../../api/types';

describe('transformWorkdayJob', () => {
  const identifier = 'nvidia/NVIDIAExternalCareerSite';
  const jobDetailBaseUrl = 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details';

  describe('Basic Transformation', () => {
    it('should transform a basic Workday job posting', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Senior Software Engineer',
        externalPath: '/job/US-CA-Santa-Clara/Senior-Software-Engineer_JR123456',
        locationsText: 'US, CA, Santa Clara',
        postedOn: 'Posted Yesterday',
        bulletFields: ['JR123456'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result).toMatchObject({
        id: 'JR123456',
        source: 'workday',
        company: 'nvidia',
        title: 'Senior Software Engineer',
        location: 'US, CA, Santa Clara',
        url: 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details/Senior-Software-Engineer_JR123456',
      });

      expect(result.createdAt).toBeTruthy();
      expect(result.classification).toBeTruthy();
      expect(result.raw).toBe(rawJob);
    });

    it('should generate ID from title when bulletFields is missing', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Software Engineer',
        externalPath: '/job/US-CA-Remote/Software-Engineer_JR999',
        locationsText: 'US, CA, Remote',
        postedOn: 'Posted Today',
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.id).toMatch(/^workday-software-engineer-\d+$/);
    });

    it('should extract company from identifier', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, 'testcompany/TestSite', jobDetailBaseUrl);

      expect(result.company).toBe('testcompany');
    });
  });

  describe('Location Handling', () => {
    it('should use specific location text', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        locationsText: 'US, CA, Santa Clara',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBe('US, CA, Santa Clara');
    });

    it('should filter out "2 Locations" text', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        locationsText: '2 Locations',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBeUndefined();
    });

    it('should filter out "3 Locations" text', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        locationsText: '3 Locations',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBeUndefined();
    });

    it('should filter out "10 Locations" text', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        locationsText: '10 Locations',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBeUndefined();
    });

    it('should filter out "1 Location" text (singular)', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        locationsText: '1 Location',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBeUndefined();
    });

    it('should handle case-insensitive location count filtering', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        locationsText: '2 LOCATIONS',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBeUndefined();
    });

    it('should handle undefined locationsText', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBeUndefined();
    });

    it('should not filter out location names that happen to contain numbers', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        locationsText: 'US, TX, Austin - Building 2',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.location).toBe('US, TX, Austin - Building 2');
    });
  });

  describe('URL Construction', () => {
    it('should construct proper job detail URL', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Software Engineer',
        externalPath: '/job/US-CA-Santa-Clara/Software-Engineer_JR123',
        bulletFields: ['JR123'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.url).toBe(
        'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details/Software-Engineer_JR123'
      );
    });

    it('should handle externalPath with multiple segments', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/US-CA-Remote/Extra-Segment/Title_JR999',
        bulletFields: ['JR999'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.url).toBe(
        'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details/Title_JR999'
      );
    });

    it('should handle externalPath without segments', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: 'Job_JR777',
        bulletFields: ['JR777'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.url).toBe(
        'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details/Job_JR777'
      );
    });
  });

  describe('Date Parsing', () => {
    it('should parse "Posted Today"', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        postedOn: 'Posted Today',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      // Should be a valid ISO 8601 date
      expect(result.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
      expect(new Date(result.createdAt).toString()).not.toBe('Invalid Date');
    });

    it('should parse "Posted Yesterday"', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        postedOn: 'Posted Yesterday',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
      expect(new Date(result.createdAt).toString()).not.toBe('Invalid Date');
    });

    it('should handle undefined postedOn', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      // Should still have a valid date (fallback behavior)
      expect(result.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
    });
  });

  describe('Role Classification', () => {
    it('should classify software engineering roles', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Senior Software Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.classification).toBeDefined();
      expect(result.classification.isSoftwareAdjacent).toBe(true);
      expect(result.classification.category).toBeTruthy();
      expect(result.classification.confidence).toBeGreaterThan(0);
    });

    it('should classify non-tech roles', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Recruiter',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.classification).toBeDefined();
      expect(result.classification.isSoftwareAdjacent).toBe(false);
      expect(result.classification.category).toBe('nonTech');
    });
  });

  describe('Edge Cases', () => {
    it('should preserve raw data', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
        customField: 'custom value',
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.raw).toBe(rawJob);
      expect((result.raw as any).customField).toBe('custom value');
    });

    it('should handle empty bulletFields array', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Software Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: [],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      // Should generate ID from title
      expect(result.id).toMatch(/^workday-software-engineer-\d+$/);
    });

    it('should handle special characters in title', () => {
      const rawJob: WorkdayJobPosting = {
        title: 'Software Engineer - AI/ML (Senior)',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      const result = transformWorkdayJob(rawJob, identifier, jobDetailBaseUrl);

      expect(result.title).toBe('Software Engineer - AI/ML (Senior)');
    });
  });
});
