import type { Job } from '../../types';
import type { AshbyJobResponse } from '../types';

/**
 * Normalize Ashby employment type to standard format
 * Ashby uses camelCase (FullTime, PartTime), we use hyphenated
 */
function normalizeEmploymentType(ashbyType: string): string {
  const typeMap: Record<string, string> = {
    FullTime: 'Full-time',
    PartTime: 'Part-time',
    Intern: 'Internship',
    Contract: 'Contract',
    Temporary: 'Temporary',
  };

  return typeMap[ashbyType] || ashbyType;
}

/**
 * Transforms Ashby API response to internal Job model
 */
export function transformAshbyJob(raw: AshbyJobResponse, companyId: string = 'notion'): Job {
  return {
    id: raw.id,
    source: 'ashby' as const,
    company: companyId,
    title: raw.title,
    department: raw.department,
    team: raw.team,
    location: raw.location,
    isRemote: raw.isRemote,
    employmentType: normalizeEmploymentType(raw.employmentType),
    createdAt: raw.publishedAt, // ISO 8601 format
    url: raw.jobUrl,
    tags: undefined, // Ashby doesn't provide tags in the response
    raw,
  };
}
