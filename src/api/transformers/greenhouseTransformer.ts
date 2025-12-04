import type { Job } from '../../types';
import type { GreenhouseJobResponse } from '../types';
import { sanitizeTags } from '../../lib/tags';

/**
 * Transforms Greenhouse API response to internal Job model
 */
export function transformGreenhouseJob(
  raw: GreenhouseJobResponse,
  companyId: string = 'spacex'
): Job {
  // Extract department (first department if multiple)
  const department = raw.departments[0]?.name;

  // Extract location (prefer office, fallback to location)
  const location = raw.offices[0]?.name || raw.location?.name;

  return {
    id: raw.id.toString(),
    source: 'greenhouse' as const,
    company: companyId,
    title: raw.title,
    department,
    location,
    createdAt: raw.first_published || raw.updated_at, // Use first_published when available
    url: raw.absolute_url,
    tags: sanitizeTags(raw.metadata?.map((m) => m.value)),
    raw,
  };
}
