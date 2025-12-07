import { useMemo } from 'react';
import { formatDistanceToNow } from 'date-fns';

/**
 * Hook for formatting job metadata
 * Memoizes date formatting to avoid unnecessary recalculations
 *
 * @param createdAt - ISO 8601 timestamp of job creation
 * @returns Object containing formatted metadata strings
 *
 * @example
 * ```tsx
 * const { postedAgo } = useJobMetadata(job.createdAt);
 * // Returns: "2 days ago", "3 hours ago", etc.
 * ```
 */
export function useJobMetadata(createdAt: string) {
  const postedAgo = useMemo(
    () => formatDistanceToNow(new Date(createdAt), { addSuffix: true }),
    [createdAt]
  );

  return { postedAgo };
}
