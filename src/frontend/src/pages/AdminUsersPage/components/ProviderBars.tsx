import Box from '@mui/material/Box';
import LinearProgress from '@mui/material/LinearProgress';
import Typography from '@mui/material/Typography';
import { PROVIDER_LABEL, type SignupProvider } from '../../../features/admin/adminApi';

interface ProviderBarsProps {
  // Partial because the aggregate omits zero-count providers. Typed as
  // ``SignupProvider`` so adding a new backend provider becomes a
  // compile-time error here instead of silently rendering a raw key.
  data: Partial<Record<SignupProvider, number>>;
}

export function ProviderBars({ data }: ProviderBarsProps) {
  const entries = (
    Object.entries(data) as [SignupProvider, number | undefined][]
  )
    .filter((e): e is [SignupProvider, number] => typeof e[1] === 'number')
    .sort((a, b) => b[1] - a[1]);
  const max = entries.reduce((m, [, v]) => Math.max(m, v), 0);

  if (entries.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No signups recorded.
      </Typography>
    );
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {entries.map(([key, count]) => {
        const pct = max === 0 ? 0 : (count / max) * 100;
        const label = PROVIDER_LABEL[key];
        return (
          <Box
            key={key}
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '110px 1fr 50px', sm: '140px 1fr 60px' },
              alignItems: 'center',
              columnGap: 2,
            }}
          >
            <Typography variant="body2">{label}</Typography>
            <LinearProgress
              variant="determinate"
              value={pct}
              sx={{ height: 8, borderRadius: 1 }}
            />
            <Typography variant="body2" align="right">
              {count.toLocaleString()}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
}
