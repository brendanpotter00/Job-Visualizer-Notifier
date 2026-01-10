import { describe, it, expect } from 'vitest';
import { transformBackendJob } from '../../../api/transformers/backendScraperTransformer';
import type { BackendJobListing } from '../../../api/types';

describe('transformBackendJob', () => {
  const mockBackendJob: BackendJobListing = {
    id: 'job-123',
    title: 'Senior Software Engineer, Cloud Platform',
    company: 'google',
    location: 'Mountain View, CA, USA',
    url: 'https://careers.google.com/jobs/results/123456',
    sourceId: 'google_scraper',
    details: JSON.stringify({
      experience_level: 'Mid-Senior',
      is_remote_eligible: true,
      minimum_qualifications: 'BS in CS',
      responsibilities: 'Design and build systems',
    }),
    createdAt: '2025-01-08T10:00:00Z',
    postedOn: null,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: '2025-01-07T08:00:00Z',
    lastSeenAt: '2025-01-08T10:00:00Z',
    consecutiveMisses: 0,
    detailsScraped: true,
  };

  it('should transform backend job correctly', () => {
    const job = transformBackendJob(mockBackendJob, 'google');

    expect(job).toMatchObject({
      id: 'job-123',
      source: 'backend-scraper',
      company: 'google',
      title: 'Senior Software Engineer, Cloud Platform',
      location: 'Mountain View, CA, USA',
      isRemote: true,
      url: 'https://careers.google.com/jobs/results/123456',
    });
  });

  it('should use provided companyId for company field', () => {
    const job = transformBackendJob(mockBackendJob, 'apple');

    expect(job.source).toBe('backend-scraper');
    expect(job.company).toBe('apple');
  });

  it('should use firstSeenAt for createdAt field', () => {
    const job = transformBackendJob(mockBackendJob, 'google');

    expect(job.createdAt).toBe('2025-01-07T08:00:00Z');
    expect(job.createdAt).not.toBe(mockBackendJob.createdAt);
  });

  it('should extract department from experience_level', () => {
    const job = transformBackendJob(mockBackendJob, 'google');

    expect(job.department).toBe('Mid-Senior');
  });

  it('should generate tags from details', () => {
    const job = transformBackendJob(mockBackendJob, 'google');

    expect(job.tags).toContain('Mid-Senior');
    expect(job.tags).toContain('Remote Eligible');
  });

  it('should handle job without remote eligibility', () => {
    const nonRemoteJob: BackendJobListing = {
      ...mockBackendJob,
      details: JSON.stringify({
        experience_level: 'Junior',
        is_remote_eligible: false,
      }),
    };

    const job = transformBackendJob(nonRemoteJob, 'google');

    expect(job.isRemote).toBe(false);
    expect(job.tags).toContain('Junior');
    expect(job.tags).not.toContain('Remote Eligible');
  });

  it('should handle malformed details JSON', () => {
    const badDetailsJob: BackendJobListing = {
      ...mockBackendJob,
      details: 'invalid json {{{',
    };

    const job = transformBackendJob(badDetailsJob, 'google');

    expect(job.id).toBe('job-123');
    expect(job.department).toBeUndefined();
    expect(job.isRemote).toBeUndefined();
    expect(job.tags).toEqual([]);
  });

  it('should handle empty details JSON', () => {
    const emptyDetailsJob: BackendJobListing = {
      ...mockBackendJob,
      details: '{}',
    };

    const job = transformBackendJob(emptyDetailsJob, 'google');

    expect(job.department).toBeUndefined();
    expect(job.isRemote).toBeUndefined();
    expect(job.tags).toEqual([]);
  });

  it('should handle null location', () => {
    const noLocationJob: BackendJobListing = {
      ...mockBackendJob,
      location: null,
    };

    const job = transformBackendJob(noLocationJob, 'google');

    expect(job.location).toBeUndefined();
  });

  it('should preserve raw response for debugging', () => {
    const job = transformBackendJob(mockBackendJob, 'google');

    expect(job.raw).toEqual(mockBackendJob);
  });

  it('should set source to backend-scraper', () => {
    const job = transformBackendJob(mockBackendJob, 'google');

    expect(job.source).toBe('backend-scraper');
  });

  it('should handle details with only experience_level', () => {
    const experienceOnlyJob: BackendJobListing = {
      ...mockBackendJob,
      details: JSON.stringify({
        experience_level: 'Senior',
      }),
    };

    const job = transformBackendJob(experienceOnlyJob, 'google');

    expect(job.department).toBe('Senior');
    expect(job.tags).toEqual(['Senior']);
    expect(job.isRemote).toBeUndefined();
  });

  it('should handle details with only is_remote_eligible', () => {
    const remoteOnlyJob: BackendJobListing = {
      ...mockBackendJob,
      details: JSON.stringify({
        is_remote_eligible: true,
      }),
    };

    const job = transformBackendJob(remoteOnlyJob, 'google');

    expect(job.department).toBeUndefined();
    expect(job.isRemote).toBe(true);
    expect(job.tags).toEqual(['Remote Eligible']);
  });

  it('should work for any companyId (extensibility test)', () => {
    // Test that the same transformer works for different companies
    const googleJob = transformBackendJob(mockBackendJob, 'google');
    const appleJob = transformBackendJob(mockBackendJob, 'apple');
    const metaJob = transformBackendJob(mockBackendJob, 'meta');

    expect(googleJob.company).toBe('google');
    expect(appleJob.company).toBe('apple');
    expect(metaJob.company).toBe('meta');

    // All should have the same source type
    expect(googleJob.source).toBe('backend-scraper');
    expect(appleJob.source).toBe('backend-scraper');
    expect(metaJob.source).toBe('backend-scraper');
  });
});
