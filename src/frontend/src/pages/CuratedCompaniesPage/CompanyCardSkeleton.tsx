import { Box, Card, CardContent, Skeleton } from '@mui/material';
import { CARD_VARIANT } from '../../components/shared/JobCard/jobCardStyles';

/** Placeholder card shown while the next batch of companies is revealed. */
export function CompanyCardSkeleton() {
  return (
    <Card variant={CARD_VARIANT} sx={{ height: '100%' }}>
      <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Skeleton variant="text" width="55%" height={28} />
        <Skeleton variant="text" width="100%" />
        <Skeleton variant="text" width="85%" />
        <Box sx={{ mt: 1 }}>
          <Skeleton variant="text" width="95%" />
          <Skeleton variant="text" width="70%" />
        </Box>
      </CardContent>
    </Card>
  );
}
