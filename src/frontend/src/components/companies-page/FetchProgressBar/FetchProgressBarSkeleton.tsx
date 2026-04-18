import { Box, Skeleton, Stack } from '@mui/material';

const CHIP_COUNT = 24;
const CHIP_WIDTHS = [72, 96, 110, 84, 128, 68, 104, 90];

export function FetchProgressBarSkeleton() {
  return (
    <Box
      sx={{
        bgcolor: 'background.paper',
        borderBottom: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        overflow: 'hidden',
        mb: 2,
        px: 2,
        py: 1.5,
      }}
    >
      <Box display="flex" justifyContent="space-between" alignItems="center">
        <Skeleton variant="text" width={220} height={24} />
        <Skeleton variant="text" width={32} height={20} />
      </Box>
      <Skeleton
        variant="rectangular"
        height={8}
        sx={{ borderRadius: 4, mt: 1, mb: 1.5 }}
      />
      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
        {Array.from({ length: CHIP_COUNT }).map((_, i) => (
          <Skeleton
            key={i}
            variant="rounded"
            width={CHIP_WIDTHS[i % CHIP_WIDTHS.length]}
            height={24}
            sx={{ borderRadius: 12 }}
          />
        ))}
      </Stack>
    </Box>
  );
}
