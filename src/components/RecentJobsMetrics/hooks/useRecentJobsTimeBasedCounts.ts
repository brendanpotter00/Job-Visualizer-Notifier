import { useMemo } from 'react';
import type { Job } from '../../../types';
import { TIME_UNITS } from '../../../constants/timeConstants';

interface RecentJobsTimeBasedCounts {
  jobsLast24Hours: number;
  jobsLast3Hours: number;
}

/**
 * Custom hook to calculate time-based job counts for Recent Jobs page
 * Calculations are deterministic based on job.createdAt timestamps
 * @param allJobs - Array of all jobs across all companies
 * @returns Memoized object with counts for 24h and 3h time windows
 */
export function useRecentJobsTimeBasedCounts(allJobs: Job[]): RecentJobsTimeBasedCounts {
  return useMemo(() => {
    const now = Date.now();
    const last24Hours = now - 24 * TIME_UNITS.HOUR;
    const last3Hours = now - 3 * TIME_UNITS.HOUR;

    return {
      jobsLast24Hours: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last24Hours)
        .length,
      jobsLast3Hours: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last3Hours)
        .length,
    };
  }, [allJobs]);
}
