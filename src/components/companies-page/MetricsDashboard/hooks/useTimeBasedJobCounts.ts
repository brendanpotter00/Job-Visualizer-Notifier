import { useMemo } from 'react';
import type { Job } from '../../../../types';
import { TIME_UNITS } from '../../../../constants/time.ts';

interface TimeBasedCounts {
  jobsLast3Days: number;
  jobsLast24Hours: number;
  jobsLast12Hours: number;
}

/**
 * Custom hook to calculate time-based job counts
 * Calculations are deterministic based on job.createdAt timestamps
 * @param allJobs - Array of all jobs for the company
 * @returns Memoized object with counts for different time windows
 */
export function useTimeBasedJobCounts(allJobs: Job[]): TimeBasedCounts {
  return useMemo(() => {
    const now = Date.now();
    const last3Days = now - 3 * TIME_UNITS.DAY;
    const last24Hours = now - 24 * TIME_UNITS.HOUR;
    const last12Hours = now - 12 * TIME_UNITS.HOUR;

    return {
      jobsLast3Days: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last3Days).length,
      jobsLast24Hours: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last24Hours)
        .length,
      jobsLast12Hours: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last12Hours)
        .length,
    };
  }, [allJobs]);
}
