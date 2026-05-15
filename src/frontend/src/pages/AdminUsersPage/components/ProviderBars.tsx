import Box from '@mui/material/Box';
import { OPS, SX } from '../adminUsersTheme';

interface ProviderBarsProps {
  data: Record<string, number>;
}

const PROVIDER_LABEL: Record<string, string> = {
  google: 'GOOGLE',
  email: 'EMAIL / AUTH0',
  other: 'OTHER',
};

const PROVIDER_COLOR: Record<string, string> = {
  google: '#60a5fa',
  email: '#fbbf24',
  other: '#94a3b8',
};

export function ProviderBars({ data }: ProviderBarsProps) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = entries.reduce((m, [, v]) => Math.max(m, v), 0);

  if (entries.length === 0) {
    return <Box sx={SX.dimMono}>No signups recorded.</Box>;
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      {entries.map(([key, count]) => {
        const widthPct = max === 0 ? 0 : (count / max) * 100;
        const label = PROVIDER_LABEL[key] ?? key.toUpperCase();
        const color = PROVIDER_COLOR[key] ?? OPS.textMuted;

        return (
          <Box
            key={key}
            sx={{
              display: 'grid',
              gridTemplateColumns: '140px 1fr 50px',
              alignItems: 'center',
              gap: 2,
            }}
          >
            <Box sx={{ ...SX.caption, color: OPS.textMuted }}>{label}</Box>
            <Box
              sx={{
                position: 'relative',
                height: 18,
                bgcolor: OPS.surfaceAlt,
                border: `1px solid ${OPS.border}`,
              }}
            >
              <Box
                sx={{
                  height: '100%',
                  width: `${widthPct}%`,
                  bgcolor: color,
                  opacity: 0.85,
                  transition: 'width 280ms ease',
                }}
              />
            </Box>
            <Box
              sx={{
                fontFamily: OPS.mono,
                fontSize: 14,
                color: OPS.textPrimary,
                textAlign: 'right',
              }}
            >
              {count}
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
