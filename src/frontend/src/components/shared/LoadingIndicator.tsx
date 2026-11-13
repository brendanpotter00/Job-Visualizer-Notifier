import { Box, CircularProgress, Skeleton, Stack, Card, CardContent } from '@mui/material';
import type { Breakpoint } from '@mui/material';
import { LoadingText } from './LoadingText';

/**
 * Props for {@link LoadingIndicator}. Modeled as a discriminated union so
 * `fullPage: true` cannot be combined with an explicit `minHeight` — the
 * full-page variant always fills the viewport. TypeScript rejects the
 * invalid combination at the call site.
 */
export type LoadingIndicatorProps =
  | {
      /** Fill the viewport (minHeight: 100vh) for page-level initial loads. */
      fullPage: true;
      caption?: string;
      /** Not allowed when `fullPage: true`. */
      minHeight?: never;
    }
  | {
      /** In-layout variant. Accepts an explicit `minHeight`. */
      fullPage?: false;
      /** Minimum height for the container (defaults to 200). */
      minHeight?: number | string;
      caption?: string;
    };

/**
 * Centered loading state: the caption (or "Loading") as a breathing wave of text,
 * with no spinner. See {@link LoadingText}. Optional full-viewport mode.
 */
export function LoadingIndicator(props: LoadingIndicatorProps) {
  const resolvedMinHeight = props.fullPage ? '100vh' : (props.minHeight ?? 200);

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        minHeight: resolvedMinHeight,
      }}
    >
      <LoadingText text={props.caption} />
    </Box>
  );
}

/**
 * Named alias of {@link LoadingIndicator}. Prefer `LoadingState` at call sites for
 * symmetry with `ErrorState` / `EmptyState`.
 */
export { LoadingIndicator as LoadingState };

/**
 * Loading skeleton for the chart/graph component
 */
export function ChartSkeleton({
  height = 400,
}: {
  height?: number | string | Partial<Record<Breakpoint, number | string>>;
} = {}) {
  return (
    <Box sx={{ width: '100%', height }} data-testid="chart-skeleton">
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
      {message && <Box sx={{ mt: 2, color: 'text.secondary', fontSize: '1rem' }}>{message}</Box>}
    </Box>
  );
}
