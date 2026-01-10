import type { Job } from '../../types';
import type { BackendJobListing, BackendJobDetails } from '../types';

/**
 * Safely parse the details JSON string from backend
 */
function parseBackendDetails(detailsString: string): BackendJobDetails {
  try {
    return JSON.parse(detailsString);
  } catch {
    return {};
  }
}

/**
 * Generate tags from job details
 */
function generateTags(details: BackendJobDetails): string[] {
  return [
    details.experience_level,
    details.is_remote_eligible ? 'Remote Eligible' : undefined,
  ].filter((tag): tag is string => Boolean(tag));
}

/**
 * Transforms backend JobListing to frontend Job model
 * Works for any backend-scraped company (Google, Apple, etc.)
 *
 * @param raw - Backend JobListing entity from PostgreSQL
 * @param companyId - Company identifier (e.g., 'google', 'apple')
 * @returns Normalized Job object for frontend consumption
 */
export function transformBackendJob(raw: BackendJobListing, companyId: string): Job {
  const details = parseBackendDetails(raw.details);

  return {
    id: raw.id,
    source: 'backend-scraper' as const,
    company: companyId,
    title: raw.title,
    department: details.experience_level,
    location: raw.location || undefined,
    isRemote: details.is_remote_eligible,
    // employmentType not available from scraper
    createdAt: raw.firstSeenAt, // Use firstSeenAt as the "posted" date
    url: raw.url,
    tags: generateTags(details),
    raw, // Preserve full backend response for debugging
  };
}
