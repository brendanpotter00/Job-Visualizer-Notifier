import { describe, it, expect } from 'vitest';
import { transformGreenhouseJob } from '../../../api/transformers/greenhouseTransformer';
import type { GreenhouseJobResponse } from '../../../api/types';

describe('transformGreenhouseJob', () => {
  const mockGreenhouseResponse: GreenhouseJobResponse = {
    id: 12345,
    title: 'Software Engineer',
    absolute_url: 'https://example.com/job/12345',
    location: { name: 'Los Angeles' },
    departments: [{ id: 1, name: 'Engineering' }],
    offices: [],
    updated_at: '2025-11-20T10:00:00Z',
  };

  it('should transform Greenhouse job correctly', () => {
    const job = transformGreenhouseJob(mockGreenhouseResponse, 'spacex');

    expect(job).toMatchObject({
      id: '12345',
      source: 'greenhouse',
      company: 'spacex',
      title: 'Software Engineer',
      location: 'Los Angeles',
      department: 'Engineering',
      createdAt: '2025-11-20T10:00:00Z',
      url: 'https://example.com/job/12345',
    });
  });

  it('should classify the job role', () => {
    const job = transformGreenhouseJob(mockGreenhouseResponse, 'spacex');

    expect(job.classification).toBeDefined();
    expect(job.classification.isSoftwareAdjacent).toBe(true);
    expect(job.classification.category).toBe('fullstack');
  });

  it('should handle jobs with offices', () => {
    const responseWithOffice: GreenhouseJobResponse = {
      ...mockGreenhouseResponse,
      offices: [{ id: 1, name: 'Hawthorne, CA', location: 'California' }],
    };

    const job = transformGreenhouseJob(responseWithOffice, 'spacex');

    expect(job.location).toBe('Hawthorne, CA');
  });

  it('should handle jobs with metadata tags', () => {
    const responseWithMetadata: GreenhouseJobResponse = {
      ...mockGreenhouseResponse,
      metadata: [
        { id: 1, name: 'tag', value: 'react' },
        { id: 2, name: 'tag', value: 'frontend' },
      ],
    };

    const job = transformGreenhouseJob(responseWithMetadata, 'spacex');

    expect(job.tags).toEqual(['react', 'frontend']);
    expect(job.classification.category).toBe('frontend');
  });

  it('should handle jobs with multiple departments', () => {
    const responseWithMultipleDepts: GreenhouseJobResponse = {
      ...mockGreenhouseResponse,
      departments: [
        { id: 1, name: 'Engineering' },
        { id: 2, name: 'Product' },
      ],
    };

    const job = transformGreenhouseJob(responseWithMultipleDepts, 'spacex');

    // Should use first department
    expect(job.department).toBe('Engineering');
  });

  it('should preserve raw response data', () => {
    const job = transformGreenhouseJob(mockGreenhouseResponse, 'spacex');

    expect(job.raw).toEqual(mockGreenhouseResponse);
  });

  it('should handle missing optional fields', () => {
    const minimalResponse: GreenhouseJobResponse = {
      id: 99999,
      title: 'Test Job',
      absolute_url: 'https://example.com/job/99999',
      location: { name: '' },
      departments: [],
      offices: [],
      updated_at: '2025-11-20T12:00:00Z',
    };

    const job = transformGreenhouseJob(minimalResponse, 'test-company');

    expect(job.id).toBe('99999');
    expect(job.company).toBe('test-company');
    expect(job.department).toBeUndefined();
    expect(job.tags).toEqual([]);
  });

  it('should filter out null values from metadata tags', () => {
    const responseWithNullTags: GreenhouseJobResponse = {
      ...mockGreenhouseResponse,
      metadata: [
        { id: 1, name: 'tag', value: 'Regular' },
        { id: 2, name: 'tag', value: 'Production' },
        { id: 3, name: 'tag', value: null },
      ],
    };

    const job = transformGreenhouseJob(responseWithNullTags, 'spacex');

    expect(job.tags).toEqual(['Regular', 'Production']);
    expect(job.tags).not.toContain(null);
  });

  it('should flatten nested arrays in metadata tags', () => {
    const responseWithNestedTags: GreenhouseJobResponse = {
      ...mockGreenhouseResponse,
      metadata: [
        { id: 1, name: 'tag', value: 'Regular' },
        { id: 2, name: 'tag', value: ['Starlink', 'Dragon'] },
        { id: 3, name: 'tag', value: 'Production' },
      ],
    };

    const job = transformGreenhouseJob(responseWithNestedTags, 'spacex');

    expect(job.tags).toEqual(['Regular', 'Starlink', 'Dragon', 'Production']);
  });

  it('should filter out empty strings from tags', () => {
    const responseWithEmptyTags: GreenhouseJobResponse = {
      ...mockGreenhouseResponse,
      metadata: [
        { id: 1, name: 'tag', value: 'Valid' },
        { id: 2, name: 'tag', value: '' },
        { id: 3, name: 'tag', value: 'AlsoValid' },
      ],
    };

    const job = transformGreenhouseJob(responseWithEmptyTags, 'spacex');

    expect(job.tags).toEqual(['Valid', 'AlsoValid']);
    expect(job.tags).not.toContain('');
  });

  it('should handle mixed null, nested arrays, and strings in tags', () => {
    const responseWithMixedTags: GreenhouseJobResponse = {
      ...mockGreenhouseResponse,
      metadata: [
        { id: 1, name: 'tag', value: 'Regular' },
        { id: 2, name: 'tag', value: 'Production' },
        { id: 3, name: 'tag', value: ['Starlink'] },
        { id: 4, name: 'tag', value: null },
        { id: 5, name: 'tag', value: '' },
        { id: 6, name: 'tag', value: 'Valid' },
      ],
    };

    const job = transformGreenhouseJob(responseWithMixedTags, 'spacex');

    expect(job.tags).toEqual(['Regular', 'Production', 'Starlink', 'Valid']);
    expect(job.tags).toHaveLength(4);
  });
});
