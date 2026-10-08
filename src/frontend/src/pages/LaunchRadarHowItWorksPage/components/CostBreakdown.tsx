import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { COMPANIES_PER_DAY, COST_PER_COMPANY, MONITORS_PER_DAY_USD, formatUsd } from '../content';

const DAYS_PER_MONTH = 30;

/** What one company costs, as a bar split by step, plus the daily and one-off costs. */
export function CostBreakdown() {
  const perCompany = COST_PER_COMPANY.reduce((sum, row) => sum + row.usd, 0);
  const perMonth = (perCompany * COMPANIES_PER_DAY + MONITORS_PER_DAY_USD) * DAYS_PER_MONTH;

  return (
    <>
      <Typography variant="body1" sx={{ fontWeight: 600, mb: 1 }}>
        About {formatUsd(perCompany)} per company
      </Typography>
      <Box
        role="img"
        aria-label={`Cost per company by step: ${COST_PER_COMPANY.map(
          (row) => `${row.step} ${formatUsd(row.usd)}`
        ).join(', ')}`}
        sx={{ display: 'flex', height: 14, borderRadius: 1, overflow: 'hidden', mb: 1.5 }}
      >
        {COST_PER_COMPANY.map((row, i) => (
          <Box
            key={row.step}
            sx={{
              width: `${(row.usd / perCompany) * 100}%`,
              bgcolor: row.color,
              borderLeft: i ? 2 : 0,
              borderColor: 'background.default',
            }}
          />
        ))}
      </Box>
      <Box component="ul" sx={{ listStyle: 'none', m: 0, mb: 2, p: 0 }}>
        {COST_PER_COMPANY.map((row) => (
          <Box
            component="li"
            key={row.step}
            sx={{
              display: 'grid',
              gridTemplateColumns: 'auto 1fr auto',
              alignItems: 'baseline',
              columnGap: 1.25,
              py: 0.75,
              borderBottom: 1,
              borderColor: 'divider',
            }}
          >
            <Box
              aria-hidden
              sx={{
                width: 10,
                height: 10,
                borderRadius: 0.5,
                bgcolor: row.color,
                alignSelf: 'center',
              }}
            />
            <Typography variant="body2">
              {row.step}
              <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                {row.detail}
              </Typography>
            </Typography>
            <Typography
              variant="body2"
              sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}
            >
              {formatUsd(row.usd)}
            </Typography>
          </Box>
        ))}
      </Box>
      <Box component="ul" sx={{ m: 0, pl: 2.25, typography: 'body2' }}>
        <li>
          <b>Daily:</b> 3 Monitors at $0.01 a day each, {formatUsd(MONITORS_PER_DAY_USD)} a day.
        </li>
        <li>
          <b>A month at {COMPANIES_PER_DAY} new companies a day:</b> about ${Math.round(perMonth)}.
        </li>
        <li>
          <b>Backfill, once:</b> $1.05 to find 20 past startups ($0.85 FindAll + $0.20 enrich), then{' '}
          {formatUsd(perCompany)} for each.
        </li>
      </Box>
    </>
  );
}
