import { Box, Typography } from '@mui/material';

interface MetricCardProps {
  value: number;
  label: string;
}

/**
 * Pure presentational component for displaying a single metric
 */
export function MetricCard({ value, label }: MetricCardProps) {
  return (
    <Box sx={{ flex: 1, textAlign: 'center' }}>
      <Typography variant="h3" component="div" gutterBottom sx={{ fontWeight: 'bold' }}>
        {value}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
    </Box>
  );
}
