import { describe, it, expect } from 'vitest';
import { transformLeverJob } from '../../../api/transformers/leverTransformer';
import type { LeverJobResponse } from '../../../api/types';

describe('transformLeverJob', () => {
  const mockLeverResponse: LeverJobResponse = {
    id: 'abc-123',
    text: 'Backend Engineer',
    hostedUrl: 'https://jobs.lever.co/nominal/abc-123',
    categories: {
      commitment: 'Full-time',
      department: 'Engineering',
      location: 'Los Angeles, CA',
      team: 'Platform',
    },
    createdAt: 1700000000000, // Nov 14, 2023
    tags: ['python', 'backend'],
    workplaceType: 'onsite',
  };

  it('should transform Lever job correctly', () => {
    const job = transformLeverJob(mockLeverResponse, 'nominal');

    expect(job).toMatchObject({
      id: 'abc-123',
      source: 'lever',
      company: 'nominal',
      title: 'Backend Engineer',
      department: 'Engineering',
      team: 'Platform',
      location: 'Los Angeles, CA',
      isRemote: false,
      employmentType: 'Full-time',
      url: 'https://jobs.lever.co/nominal/abc-123',
      tags: ['python', 'backend'],
    });
  });

  it('should convert Unix timestamp to ISO string', () => {
    const job = transformLeverJob(mockLeverResponse, 'nominal');

    expect(job.createdAt).toBe('2023-11-14T22:13:20.000Z');
  });

  it('should classify the job role', () => {
    const job = transformLeverJob(mockLeverResponse, 'nominal');

    expect(job.classification).toBeDefined();
    expect(job.classification.isSoftwareAdjacent).toBe(true);
    expect(job.classification.category).toBe('backend');
  });

  it('should handle remote jobs', () => {
    const remoteResponse: LeverJobResponse = {
      ...mockLeverResponse,
      workplaceType: 'remote',
    };

    const job = transformLeverJob(remoteResponse, 'nominal');

    expect(job.isRemote).toBe(true);
  });

  it('should handle unspecified workplace type', () => {
    const unspecifiedResponse: LeverJobResponse = {
      ...mockLeverResponse,
      workplaceType: 'unspecified',
    };

    const job = transformLeverJob(unspecifiedResponse, 'nominal');

    expect(job.isRemote).toBe(false);
  });

  it('should preserve raw response data', () => {
    const job = transformLeverJob(mockLeverResponse, 'nominal');

    expect(job.raw).toEqual(mockLeverResponse);
  });

  it('should handle missing optional fields', () => {
    const minimalResponse: LeverJobResponse = {
      id: 'xyz-789',
      text: 'Software Engineer',
      hostedUrl: 'https://jobs.lever.co/company/xyz-789',
      categories: {},
      createdAt: 1700000000000,
    };

    const job = transformLeverJob(minimalResponse, 'company');

    expect(job.id).toBe('xyz-789');
    expect(job.company).toBe('company');
    expect(job.title).toBe('Software Engineer');
    expect(job.department).toBeUndefined();
    expect(job.team).toBeUndefined();
    expect(job.location).toBeUndefined();
    expect(job.employmentType).toBeUndefined();
    expect(job.tags).toEqual([]);
  });

  it('should handle frontend roles with tags', () => {
    const frontendResponse: LeverJobResponse = {
      ...mockLeverResponse,
      text: 'Frontend Developer',
      tags: ['react', 'javascript', 'typescript'],
    };

    const job = transformLeverJob(frontendResponse, 'nominal');

    expect(job.classification.category).toBe('frontend');
    expect(job.tags).toEqual(['react', 'javascript', 'typescript']);
  });

  it('should filter out null values from tags', () => {
    const responseWithNullTags: LeverJobResponse = {
      ...mockLeverResponse,
      tags: ['Regular', 'Production', null, 'Valid'] as any,
    };

    const job = transformLeverJob(responseWithNullTags, 'nominal');

    expect(job.tags).toEqual(['Regular', 'Production', 'Valid']);
    expect(job.tags).not.toContain(null);
  });

  it('should flatten nested arrays in tags', () => {
    const responseWithNestedTags: LeverJobResponse = {
      ...mockLeverResponse,
      tags: ['Regular', ['Starlink', 'Dragon'], 'Production'] as any,
    };

    const job = transformLeverJob(responseWithNestedTags, 'nominal');

    expect(job.tags).toEqual(['Regular', 'Starlink', 'Dragon', 'Production']);
  });

  it('should filter out empty strings from tags', () => {
    const responseWithEmptyTags: LeverJobResponse = {
      ...mockLeverResponse,
      tags: ['Valid', '', 'AlsoValid'] as any,
    };

    const job = transformLeverJob(responseWithEmptyTags, 'nominal');

    expect(job.tags).toEqual(['Valid', 'AlsoValid']);
    expect(job.tags).not.toContain('');
  });

  it('should handle mixed null, nested arrays, and strings in tags', () => {
    const responseWithMixedTags: LeverJobResponse = {
      ...mockLeverResponse,
      tags: ['Regular', 'Production', ['Starlink'], null, '', 'Valid'] as any,
    };

    const job = transformLeverJob(responseWithMixedTags, 'nominal');

    expect(job.tags).toEqual(['Regular', 'Production', 'Starlink', 'Valid']);
    expect(job.tags).toHaveLength(4);
  });
});
