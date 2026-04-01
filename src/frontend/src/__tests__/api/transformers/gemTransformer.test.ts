import { describe, it, expect } from 'vitest';
import { transformGemJob } from '../../../api/transformers/gemTransformer';
import type { GemJobResponse } from '../../../api/types';

describe('transformGemJob', () => {
  const mockGemJob: GemJobResponse = {
    id: '37c9854b-f1ea-4da6-a3f5-51e64923ae08',
    title: 'Software Engineer',
    absolute_url: 'https://jobs.gem.com/nominal/37c9854b-f1ea-4da6-a3f5-51e64923ae08',
    content: '<p>Job description HTML</p>',
    content_plain: 'Job description plain text',
    created_at: '2025-03-06T17:24:22.000Z',
    updated_at: '2025-11-21T10:00:00.000Z',
    first_published_at: '2025-03-06T17:24:22.000Z',
    employment_type: 'full_time',
    location_type: 'in_office',
    location: { name: 'New York, United States' },
    departments: [
      { id: 'dept-1', name: 'Engineering' },
    ],
    offices: [
      {
        id: 'office-1',
        name: 'New York, NY',
        location: { name: 'New York, United States' },
      },
      {
        id: 'office-2',
        name: 'Los Angeles, CA',
        location: { name: 'Los Angeles, United States' },
      },
    ],
    internal_job_id: '37c9854b-f1ea-4da6-a3f5-51e64923ae08',
    requisition_id: 'R67',
  };

  it('should transform a Gem job response to the internal Job model', () => {
    const result = transformGemJob(mockGemJob, 'nominal');

    expect(result.id).toBe('37c9854b-f1ea-4da6-a3f5-51e64923ae08');
    expect(result.source).toBe('gem');
    expect(result.company).toBe('nominal');
    expect(result.title).toBe('Software Engineer');
    expect(result.department).toBe('Engineering');
    expect(result.url).toBe('https://jobs.gem.com/nominal/37c9854b-f1ea-4da6-a3f5-51e64923ae08');
    expect(result.raw).toBe(mockGemJob);
  });

  it('should prefer offices[0].name over location.name for location', () => {
    const result = transformGemJob(mockGemJob, 'nominal');
    expect(result.location).toBe('New York, NY');
  });

  it('should fall back to location.name when office name is empty string', () => {
    const jobWithEmptyOfficeName: GemJobResponse = {
      ...mockGemJob,
      offices: [
        {
          id: 'office-1',
          name: '',
          location: { name: '' },
        },
      ],
    };
    const result = transformGemJob(jobWithEmptyOfficeName, 'nominal');
    expect(result.location).toBe('New York, United States');
  });

  it('should fall back to location.name when offices array is empty', () => {
    const jobWithNoOffices: GemJobResponse = {
      ...mockGemJob,
      offices: [],
    };
    const result = transformGemJob(jobWithNoOffices, 'nominal');
    expect(result.location).toBe('New York, United States');
  });

  it('should handle null location when offices array is empty', () => {
    const jobWithNoLocation: GemJobResponse = {
      ...mockGemJob,
      offices: [],
      location: null,
    };
    const result = transformGemJob(jobWithNoLocation, 'nominal');
    expect(result.location).toBeUndefined();
  });

  it('should detect remote jobs via location_type', () => {
    const remoteJob: GemJobResponse = {
      ...mockGemJob,
      location_type: 'remote',
    };
    const result = transformGemJob(remoteJob, 'nominal');
    expect(result.isRemote).toBe(true);
  });

  it('should set isRemote to false for non-remote location_type', () => {
    const result = transformGemJob(mockGemJob, 'nominal');
    expect(result.isRemote).toBe(false);
  });

  it('should normalize full_time employment type to Full-time', () => {
    const result = transformGemJob(mockGemJob, 'nominal');
    expect(result.employmentType).toBe('Full-time');
  });

  it('should normalize part_time employment type to Part-time', () => {
    const partTimeJob: GemJobResponse = {
      ...mockGemJob,
      employment_type: 'part_time',
    };
    const result = transformGemJob(partTimeJob, 'nominal');
    expect(result.employmentType).toBe('Part-time');
  });

  it('should normalize contract employment type to Contract', () => {
    const contractJob: GemJobResponse = {
      ...mockGemJob,
      employment_type: 'contract',
    };
    const result = transformGemJob(contractJob, 'nominal');
    expect(result.employmentType).toBe('Contract');
  });

  it('should normalize intern employment type to Internship', () => {
    const internJob: GemJobResponse = {
      ...mockGemJob,
      employment_type: 'intern',
    };
    const result = transformGemJob(internJob, 'nominal');
    expect(result.employmentType).toBe('Internship');
  });

  it('should pass through unknown employment types unchanged', () => {
    const unknownTypeJob: GemJobResponse = {
      ...mockGemJob,
      employment_type: 'freelance',
    };
    const result = transformGemJob(unknownTypeJob, 'nominal');
    expect(result.employmentType).toBe('freelance');
  });

  it('should return undefined for null employment type', () => {
    const nullTypeJob: GemJobResponse = {
      ...mockGemJob,
      employment_type: null,
    };
    const result = transformGemJob(nullTypeJob, 'nominal');
    expect(result.employmentType).toBeUndefined();
  });

  it('should prefer first_published_at over created_at for createdAt', () => {
    const result = transformGemJob(mockGemJob, 'nominal');
    expect(result.createdAt).toBe('2025-03-06T17:24:22.000Z');
  });

  it('should fall back to created_at when first_published_at is null', () => {
    const jobWithNoPublished: GemJobResponse = {
      ...mockGemJob,
      first_published_at: null,
      created_at: '2025-01-15T12:00:00.000Z',
    };
    const result = transformGemJob(jobWithNoPublished, 'nominal');
    expect(result.createdAt).toBe('2025-01-15T12:00:00.000Z');
  });

  it('should use first department when multiple departments exist', () => {
    const multiDeptJob: GemJobResponse = {
      ...mockGemJob,
      departments: [
        { id: 'dept-1', name: 'Engineering' },
        { id: 'dept-2', name: 'Product' },
      ],
    };
    const result = transformGemJob(multiDeptJob, 'nominal');
    expect(result.department).toBe('Engineering');
  });

  it('should handle empty departments array', () => {
    const noDeptJob: GemJobResponse = {
      ...mockGemJob,
      departments: [],
    };
    const result = transformGemJob(noDeptJob, 'nominal');
    expect(result.department).toBeUndefined();
  });

  it('should set tags to undefined (Gem does not provide structured tags)', () => {
    const result = transformGemJob(mockGemJob, 'nominal');
    expect(result.tags).toBeUndefined();
  });

  it('should handle minimal response with null/empty optional fields', () => {
    const minimalJob: GemJobResponse = {
      id: 'min-id',
      title: 'Minimal Job',
      absolute_url: 'https://jobs.gem.com/test/min-id',
      content: '',
      content_plain: '',
      created_at: '2025-06-01T00:00:00.000Z',
      updated_at: '2025-06-01T00:00:00.000Z',
      first_published_at: null,
      employment_type: null,
      location_type: null,
      location: null,
      departments: [],
      offices: [],
      internal_job_id: 'min-id',
      requisition_id: '',
    };
    const result = transformGemJob(minimalJob, 'test-co');

    expect(result.id).toBe('min-id');
    expect(result.source).toBe('gem');
    expect(result.company).toBe('test-co');
    expect(result.title).toBe('Minimal Job');
    expect(result.department).toBeUndefined();
    expect(result.location).toBeUndefined();
    expect(result.isRemote).toBe(false);
    expect(result.employmentType).toBeUndefined();
    expect(result.createdAt).toBe('2025-06-01T00:00:00.000Z');
  });
});
