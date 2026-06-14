import { Box, Card, CardContent, Skeleton, Stack } from '@mui/material';
import { ARIA_LABELS } from '../../constants/messages';

interface ChangelogSkeletonsProps {
  /**
   * Number of skeleton cards to render
   */
  count: number;
}

/**
 * Loading skeleton placeholders for changelog cards.
 * Mirrors the layout of the real entry card in ChangelogColumn (title + date
 * row, description lines, tag chips) so the loading state feels intentional
 * rather than a generic shimmer.
 */
export function ChangelogSkeletons({ count }: ChangelogSkeletonsProps) {
  return (
    <Stack spacing={2} role="status" aria-label={ARIA_LABELS.LOADING_MORE_CHANGELOG}>
      {Array.from({ length: count }).map((_, index) => (
        <Card key={`changelog-skeleton-${index}`} variant="outlined" aria-hidden="true">
          <CardContent>
            {/* Title + date row */}
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="flex-start"
              spacing={2}
              sx={{ mb: 1 }}
            >
              <Skeleton variant="text" width="55%" height={28} />
              <Skeleton variant="text" width={80} height={20} />
            </Stack>

            {/* Description lines */}
            <Skeleton variant="text" width="100%" height={18} />
            <Skeleton variant="text" width="85%" height={18} sx={{ mb: 1.5 }} />

            {/* Tag chips */}
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <Skeleton variant="rounded" width={64} height={24} />
              <Skeleton variant="rounded" width={88} height={24} />
            </Box>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}
