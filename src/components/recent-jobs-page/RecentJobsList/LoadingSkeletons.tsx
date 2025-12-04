import { Card, CardContent, Skeleton, Stack } from '@mui/material';

/**
 * Props for LoadingSkeletons component
 */
interface LoadingSkeletonsProps {
  /**
   * Number of skeleton cards to render
   */
  count: number;
}

/**
 * Loading skeleton placeholders for job cards
 * Matches the layout of RecentJobCard for consistent visual flow
 */
export function LoadingSkeletons({ count }: LoadingSkeletonsProps) {
  return (
    <div role="status" aria-label="Loading more jobs">
      {Array.from({ length: count }).map((_, index) => (
        <Card key={`skeleton-${index}`} variant="outlined" sx={{ mb: 2 }} aria-hidden="true">
          <CardContent>
            {/* Company name skeleton */}
            <Skeleton variant="text" width="30%" height={20} sx={{ mb: 1 }} />

            {/* Job title skeleton */}
            <Skeleton variant="text" width="70%" height={32} sx={{ mb: 1 }} />

            {/* Location and employment type skeleton */}
            <Skeleton variant="text" width="50%" height={20} sx={{ mb: 1 }} />

            {/* Chips skeleton */}
            <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
              <Skeleton variant="rounded" width={80} height={24} />
              <Skeleton variant="rounded" width={70} height={24} />
              <Skeleton variant="rounded" width={90} height={24} />
            </Stack>

            {/* Posted date skeleton */}
            <Skeleton variant="text" width="40%" height={16} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
