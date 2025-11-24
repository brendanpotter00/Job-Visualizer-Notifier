import { useMemo } from 'react';
import type { Job } from '../../../types';

interface TimeBasedCounts {
  jobsLast3Days: number;
  jobsLast24Hours: number;
  jobsLast12Hours: number;
}

/**
 * Custom hook to calculate time-based job counts
 * @param allJobs - Array of all jobs for the company
 * @param currentTime - Current timestamp in milliseconds
 * @returns Memoized object with counts for different time windows
 */
export function useTimeBasedJobCounts(allJobs: Job[], currentTime: number): TimeBasedCounts {
  return useMemo(() => {
    const last3Days = currentTime - 3 * 24 * 60 * 60 * 1000;
    const last24Hours = currentTime - 24 * 60 * 60 * 1000;
    const last12Hours = currentTime - 12 * 60 * 60 * 1000;

    return {
      jobsLast3Days: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last3Days).length,
      jobsLast24Hours: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last24Hours)
        .length,
      jobsLast12Hours: allJobs.filter((job) => new Date(job.createdAt).getTime() >= last12Hours)
        .length,
    };
  }, [allJobs, currentTime]);
}
