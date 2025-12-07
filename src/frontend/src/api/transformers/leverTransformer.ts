import type { Job } from '../../types';
import type { LeverJobResponse } from '../types';
import { sanitizeTags } from '../../lib/tags';

/**
 * Transforms Lever API response to internal Job model
 */
export function transformLeverJob(raw: LeverJobResponse, companyId: string): Job {
  return {
    id: raw.id,
    source: 'lever' as const,
    company: companyId,
    title: raw.text,
    department: raw.categories.department,
    team: raw.categories.team,
    location: raw.categories.location,
    isRemote: raw.workplaceType === 'remote',
    employmentType: raw.categories.commitment,
    createdAt: new Date(raw.createdAt).toISOString(),
    url: raw.hostedUrl,
    tags: sanitizeTags(raw.tags),
    raw,
  };
}
