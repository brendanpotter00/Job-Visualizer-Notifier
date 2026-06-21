import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import { TimeWindowSelect } from '../shared/filters/TimeWindowSelect.tsx';
import type { TimeWindow } from '../../types';

export interface TimeWindowDefaultsProps {
  recentTimeWindow: TimeWindow;
  trendTimeWindow: TimeWindow;
  onChangeRecent: (tw: TimeWindow) => void;
  onChangeTrend: (tw: TimeWindow) => void;
}

/**
 * Per-page default time windows. The Recent Jobs page and the Company Hiring
 * Trends page each get their own saved default; they are independent.
 */
export function TimeWindowDefaults({
  recentTimeWindow,
  trendTimeWindow,
  onChangeRecent,
  onChangeTrend,
}: TimeWindowDefaultsProps) {
  return (
    <Paper sx={{ p: 4 }}>
      <Typography variant="h6" gutterBottom>
        Default time windows
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Applied when you open each page. The two pages keep separate defaults.
      </Typography>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3}>
        <TimeWindowSelect
          value={recentTimeWindow}
          onChange={onChangeRecent}
          label="Recent Jobs default"
        />
        <TimeWindowSelect
          value={trendTimeWindow}
          onChange={onChangeTrend}
          label="Company Trends default"
        />
      </Stack>
    </Paper>
  );
}
