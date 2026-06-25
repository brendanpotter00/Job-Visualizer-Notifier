import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../../config/responsive';

interface StatTileProps {
  label: string;
  value: React.ReactNode;
  meta?: React.ReactNode;
  decoration?: React.ReactNode;
}

export function StatTile({ label, value, meta, decoration }: StatTileProps) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: RESPONSIVE.statTile.padding,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        gap: RESPONSIVE.statTile.gap,
      }}
    >
      <Typography
        variant="overline"
        color="text.secondary"
        sx={{ lineHeight: 1.2 }}
      >
        {label}
      </Typography>
      <Typography variant="h4" component="div" sx={{ fontWeight: 500 }}>
        {value}
      </Typography>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 2,
          minHeight: 24,
        }}
      >
        <Typography variant="body2" color="text.secondary">
          {meta}
        </Typography>
        {decoration}
      </Box>
    </Paper>
  );
}
