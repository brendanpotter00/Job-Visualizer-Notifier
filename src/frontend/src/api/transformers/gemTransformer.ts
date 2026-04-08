import type { Job } from '../../types';
import type { GemJobResponse } from '../types';

/**
 * Normalize Gem employment type to standard format.
 * Gem uses snake_case (full_time, part_time); we use hyphenated display format.
 */
function normalizeEmploymentType(gemType: string | null): string | undefined {
  if (!gemType) return undefined;
  const typeMap: Record<string, string> = {
    full_time: 'Full-time',
    part_time: 'Part-time',
    contract: 'Contract',
    intern: 'Internship',
    temporary: 'Temporary',
  };
  return typeMap[gemType] || gemType;
}

/**
 * Transforms a Gem API job response to the internal Job model.
 * Structure is similar to Greenhouse (departments array, offices array, location object).
 */
export function transformGemJob(raw: GemJobResponse, companyId: string): Job {
  return {
    id: String(raw.id),
    source: 'gem' as const,
    company: companyId,
    title: raw.title,
    department: raw.departments?.[0]?.name,
    location: raw.offices?.[0]?.name ?? raw.location?.name,
    isRemote: raw.location_type === 'remote',
    employmentType: normalizeEmploymentType(raw.employment_type),
    createdAt: raw.first_published_at || raw.created_at,
    url: raw.absolute_url,
    tags: undefined,
    raw,
  };
}
