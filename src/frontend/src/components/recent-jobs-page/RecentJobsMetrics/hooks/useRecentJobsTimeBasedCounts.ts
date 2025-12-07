import { useMemo } from 'react';
import type { Job } from '../../../../types';
import { filterJobsByHours } from '../../../../lib/date.ts';

interface RecentJobsTimeBasedCounts {
  jobsLast24Hours: number;
  jobsLast3Hours: number;
}

/**
 * Custom hook to calculate time-based job counts for Recent Jobs page
 * Calculations are deterministic based on job.createdAt timestamps
 * Uses shared filterJobsByHours utility for consistency with other filtering logic
 *
 * @param allJobs - Array of all jobs across all companies
 * @returns Memoized object with counts for 24h and 3h time windows
 */
export function useRecentJobsTimeBasedCounts(allJobs: Job[]): RecentJobsTimeBasedCounts {
  return useMemo(() => {
    return {
      jobsLast24Hours: filterJobsByHours(allJobs, 24).length,
      jobsLast3Hours: filterJobsByHours(allJobs, 3).length,
    };
  }, [allJobs]);
}
