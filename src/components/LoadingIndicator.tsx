import { Box, CircularProgress, Skeleton, Stack, Card, CardContent } from '@mui/material';

interface LoadingIndicatorProps {
  /** Size of the spinner */
  size?: number;

  /** Minimum height for the container */
  minHeight?: number | string;
}

/**
 * Centered loading spinner
 */
export function LoadingIndicator({ size = 40, minHeight = 200 }: LoadingIndicatorProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight,
      }}
    >
      <CircularProgress size={size} />
    </Box>
  );
}

/**
 * Loading skeleton for the chart/graph component
 */
export function ChartSkeleton() {
  return (
    <Box sx={{ width: '100%', height: 400 }}>
      <Skeleton variant="rectangular" width="100%" height="100%" />
    </Box>
  );
}

/**
 * Loading skeleton for a job card
 */
export function JobCardSkeleton() {
  return (
    <Card>
      <CardContent>
        <Skeleton variant="text" width="70%" height={28} sx={{ mb: 1 }} />
        <Skeleton variant="text" width="40%" height={20} sx={{ mb: 2 }} />
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <Skeleton variant="rectangular" width={80} height={24} sx={{ borderRadius: 0.5 }} />
          <Skeleton variant="rectangular" width={100} height={24} sx={{ borderRadius: 0.5 }} />
          <Skeleton variant="rectangular" width={60} height={24} sx={{ borderRadius: 0.5 }} />
        </Stack>
        <Skeleton variant="text" width="30%" height={20} />
      </CardContent>
    </Card>
  );
}

/**
 * Loading skeleton for multiple job cards
 */
export function JobListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <Stack spacing={2}>
      {Array.from({ length: count }).map((_, index) => (
        <JobCardSkeleton key={index} />
      ))}
    </Stack>
  );
}

/**
 * Loading overlay (for global loading state)
 */
export function LoadingOverlay({ message }: { message?: string }) {
  return (
    <Box
      sx={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'rgba(255, 255, 255, 0.9)',
        zIndex: 9999,
      }}
    >
      <CircularProgress size={60} />
      {message && (
        <Box sx={{ mt: 2, color: 'text.secondary', fontSize: '1rem' }}>{message}</Box>
      )}
    </Box>
  );
}
