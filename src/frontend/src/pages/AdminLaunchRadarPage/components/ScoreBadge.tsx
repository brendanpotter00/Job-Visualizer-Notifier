import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';

interface ScoreBadgeProps {
  label: string;
  /** 0–100, or null when there was no data to score. */
  value: number | null;
}

/**
 * A big tabular numeral over a 30x3 bar filled to `value%`, then a small label.
 * `null` means "no data", which is NOT the same claim as 0: it renders a grey
 * dash over an empty bar so a card with no people data never reads as a
 * zero-talent company.
 */
export function ScoreBadge({ label, value }: ScoreBadgeProps) {
  const hasValue = value != null;
  const pct = hasValue ? Math.max(0, Math.min(100, value)) : 0;
  return (
    <Box
      sx={{ textAlign: 'center', minWidth: 30 }}
      role="group"
      aria-label={hasValue ? `${label} score ${value}` : `${label}: No score`}
    >
      <Typography
        component="div"
        aria-label={hasValue ? undefined : 'No score'}
        sx={{
          fontSize: 22,
          fontWeight: 600,
          lineHeight: 1,
          fontVariantNumeric: 'tabular-nums',
          color: hasValue ? 'text.primary' : 'text.disabled',
        }}
      >
        {hasValue ? value : '–'}
      </Typography>
      <Box
        sx={{
          width: 30,
          height: 3,
          bgcolor: 'action.hover',
          borderRadius: 1,
          mx: 'auto',
          mt: 0.75,
          mb: 0.375,
          overflow: 'hidden',
        }}
      >
        {hasValue && <Box sx={{ width: `${pct}%`, height: '100%', bgcolor: 'text.primary' }} />}
      </Box>
      <Typography component="div" sx={{ fontSize: 11, color: 'text.secondary' }}>
        {label}
      </Typography>
    </Box>
  );
}
