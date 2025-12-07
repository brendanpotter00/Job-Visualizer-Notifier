import { describe, it, expect } from 'vitest';
import { transformAshbyJob } from '../../../api/transformers/ashbyTransformer';
import type { AshbyJobResponse } from '../../../api/types';

describe('transformAshbyJob', () => {
  const mockAshbyJob: AshbyJobResponse = {
    id: '26a55f5f-8022-4f65-a3dd-b876e01bc456',
    title: 'Senior Software Engineer',
    jobUrl: 'https://jobs.ashbyhq.com/notion/26a55f5f-8022-4f65-a3dd-b876e01bc456',
    applyUrl: 'https://jobs.ashbyhq.com/notion/26a55f5f-8022-4f65-a3dd-b876e01bc456/application',
    publishedAt: '2025-11-20T10:30:00Z',
    location: 'San Francisco, CA',
    department: 'Engineering',
    team: 'Platform',
    employmentType: 'FullTime',
    isRemote: false,
    isListed: true,
    descriptionHtml: '<p>Join our team...</p>',
    descriptionPlain: 'Join our team...',
  };

  it('should transform Ashby job response to internal Job model', () => {
    const result = transformAshbyJob(mockAshbyJob, 'notion');

    expect(result.id).toBe(mockAshbyJob.id);
    expect(result.source).toBe('ashby');
    expect(result.company).toBe('notion');
    expect(result.title).toBe(mockAshbyJob.title);
    expect(result.department).toBe(mockAshbyJob.department);
    expect(result.team).toBe(mockAshbyJob.team);
    expect(result.location).toBe(mockAshbyJob.location);
    expect(result.isRemote).toBe(mockAshbyJob.isRemote);
    expect(result.createdAt).toBe(mockAshbyJob.publishedAt);
    expect(result.url).toBe(mockAshbyJob.jobUrl);
    expect(result.raw).toBe(mockAshbyJob);
  });

  it('should normalize FullTime employment type to Full-time', () => {
    const result = transformAshbyJob(mockAshbyJob, 'notion');
    expect(result.employmentType).toBe('Full-time');
  });

  it('should normalize PartTime employment type to Part-time', () => {
    const partTimeJob: AshbyJobResponse = {
      ...mockAshbyJob,
      employmentType: 'PartTime',
    };

    const result = transformAshbyJob(partTimeJob, 'notion');
    expect(result.employmentType).toBe('Part-time');
  });

  it('should normalize Intern employment type to Internship', () => {
    const internJob: AshbyJobResponse = {
      ...mockAshbyJob,
      employmentType: 'Intern',
    };

    const result = transformAshbyJob(internJob, 'notion');
    expect(result.employmentType).toBe('Internship');
  });

  it('should keep Contract and Temporary employment types unchanged', () => {
    const contractJob: AshbyJobResponse = {
      ...mockAshbyJob,
      employmentType: 'Contract',
    };
    const tempJob: AshbyJobResponse = {
      ...mockAshbyJob,
      employmentType: 'Temporary',
    };

    expect(transformAshbyJob(contractJob, 'notion').employmentType).toBe('Contract');
    expect(transformAshbyJob(tempJob, 'notion').employmentType).toBe('Temporary');
  });

  it('should handle optional fields being undefined', () => {
    const minimalJob: AshbyJobResponse = {
      id: 'test-id',
      title: 'Test Role',
      jobUrl: 'https://jobs.ashbyhq.com/notion/test',
      applyUrl: 'https://jobs.ashbyhq.com/notion/test/application',
      publishedAt: '2025-11-20T10:30:00Z',
      location: 'Remote',
      employmentType: 'FullTime',
      isListed: true,
      descriptionHtml: '<p>Test</p>',
      descriptionPlain: 'Test',
    };

    const result = transformAshbyJob(minimalJob, 'notion');

    expect(result.department).toBeUndefined();
    expect(result.team).toBeUndefined();
    expect(result.isRemote).toBeUndefined();
  });

  it('should set tags to undefined (Ashby does not provide tags)', () => {
    const result = transformAshbyJob(mockAshbyJob, 'notion');
    expect(result.tags).toBeUndefined();
  });

  it('should transform basic job properties', () => {
    const result = transformAshbyJob(mockAshbyJob, 'notion');

    expect(result.id).toBe('26a55f5f-8022-4f65-a3dd-b876e01bc456');
    expect(result.title).toBe('Senior Software Engineer');
    expect(result.source).toBe('ashby');
    expect(result.company).toBe('notion');
  });

  it('should handle remote jobs', () => {
    const remoteJob: AshbyJobResponse = {
      ...mockAshbyJob,
      isRemote: true,
      location: 'Remote',
    };

    const result = transformAshbyJob(remoteJob, 'notion');

    expect(result.isRemote).toBe(true);
    expect(result.location).toBe('Remote');
  });

  it('should preserve ISO 8601 timestamp format', () => {
    const result = transformAshbyJob(mockAshbyJob, 'notion');

    // Should be valid ISO 8601 string
    expect(result.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
    expect(new Date(result.createdAt).toISOString()).toBeTruthy();
  });

  it('should use default company ID when not provided', () => {
    const result = transformAshbyJob(mockAshbyJob);
    expect(result.company).toBe('notion');
  });

  it('should handle frontend role', () => {
    const frontendJob: AshbyJobResponse = {
      ...mockAshbyJob,
      title: 'Senior Frontend Engineer',
    };

    const result = transformAshbyJob(frontendJob, 'notion');

    expect(result.title).toBe('Senior Frontend Engineer');
  });

  it('should handle non-tech roles', () => {
    const salesJob: AshbyJobResponse = {
      ...mockAshbyJob,
      title: 'Sales Representative',
      department: 'Sales',
    };

    const result = transformAshbyJob(salesJob, 'notion');

    expect(result.title).toBe('Sales Representative');
    expect(result.department).toBe('Sales');
  });
});
