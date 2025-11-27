import type { Job } from '../../types';
import type { WorkdayJobPosting } from '../types';
import { classifyJobRole } from '../../utils/roleClassification';
import { parseWorkdayDate } from '../../utils/workdayDateParser';

/**
 * Transforms a Workday job posting into the normalized Job model
 *
 * @param raw - Raw Workday job posting from API
 * @param identifier - Company identifier (tenantSlug/careerSiteSlug)
 * @param jobDetailBaseUrl - Base URL for job detail pages (e.g., "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details")
 * @returns Normalized Job object with classification
 *
 * @example
 * transformWorkdayJob(
 *   {
 *     title: "Software Engineer",
 *     externalPath: "/job/US-CA-Remote/Software-Engineer_JR123456",
 *     ...
 *   },
 *   "nvidia/NVIDIAExternalCareerSite",
 *   "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details"
 * )
 * // Returns job with URL: "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details/Software-Engineer_JR123456"
 */
export function transformWorkdayJob(
  raw: WorkdayJobPosting,
  identifier: string,
  jobDetailBaseUrl: string
): Job {
  // Extract job ID from bulletFields (first element is typically requisition ID)
  // Fallback to generating ID from title if not available
  const id =
    raw.bulletFields?.[0] ||
    `workday-${raw.title.replace(/\s+/g, '-').toLowerCase()}-${Date.now()}`;

  // Extract job title+ID from externalPath (last segment after final /)
  // Example: "/job/US-CA-Santa-Clara/Title_JR123" → "Title_JR123"
  const jobTitleId = raw.externalPath.split('/').pop() || raw.externalPath;

  // Construct proper job detail URL
  // Example: "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details" + "/Title_JR123"
  const url = `${jobDetailBaseUrl}/${jobTitleId}`;

  // Parse Workday's relative date format into ISO 8601
  const createdAt = parseWorkdayDate(raw.postedOn);

  // Extract company identifier (first part before slash)
  const company = identifier.split('/')[0];

  // Create job without classification first
  const jobWithoutClassification = {
    id,
    source: 'workday' as const,
    company,
    title: raw.title,
    location: raw.locationsText,
    createdAt,
    url,
    raw,
  };

  // Classify the role using existing classification system
  const classification = classifyJobRole(jobWithoutClassification);

  return {
    ...jobWithoutClassification,
    classification,
  };
}
