import { Fragment } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import {
  COMPANIES_PER_DAY,
  COST_PER_COMPANY,
  MONITORS_PER_DAY_USD,
  OPUS_AGENT,
  PARALLEL_COLOR,
  formatUsd,
} from '../content';

const DAYS_PER_MONTH = 30;

/** The same card from a Claude Opus agent instead: what it costs, and what it got right and wrong. */
function OpusComparison({ parallelUsd }: { parallelUsd: number }) {
  const rows = [
    { name: 'Parallel', usd: parallelUsd, label: formatUsd(parallelUsd), color: PARALLEL_COLOR },
    {
      name: 'Opus agent',
      usd: OPUS_AGENT.usdPerCompany,
      label: `~${formatUsd(OPUS_AGENT.usdPerCompany)}`,
      color: OPUS_AGENT.color,
    },
  ];
  const max = Math.max(...rows.map((row) => row.usd));
  return (
    <Box sx={{ borderTop: 1, borderColor: 'divider', mt: 2, pt: 2 }}>
      <Typography variant="body1" sx={{ fontWeight: 600, mb: 1 }}>
        An Opus agent: about {formatUsd(OPUS_AGENT.usdPerCompany)} per company
      </Typography>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: 'max-content 1fr max-content',
          alignItems: 'center',
          columnGap: 1.5,
          rowGap: 1,
          mb: 2,
        }}
      >
        {rows.map((row) => (
          <Fragment key={row.name}>
            <Typography variant="body2" color="text.secondary">
              {row.name}
            </Typography>
            <Box
              aria-hidden
              sx={{ height: 14, bgcolor: 'background.paper', borderRadius: 1, overflow: 'hidden' }}
            >
              <Box
                sx={{ width: `${(row.usd / max) * 100}%`, height: '100%', bgcolor: row.color }}
              />
            </Box>
            <Typography
              variant="body2"
              sx={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}
            >
              {row.label}
            </Typography>
          </Fragment>
        ))}
      </Box>
      <Box component="ul" sx={{ m: 0, pl: 2.25, typography: 'body2' }}>
        <li>
          The same Raindrop card, researched by a Claude Opus 5.5 agent with web search:{' '}
          {OPUS_AGENT.searches} searches and {OPUS_AGENT.fetches} page fetches.
        </li>
        <li>
          <b>Better:</b> it caught that Opyn's sale was not the founders' exit.
        </li>
        <li>
          <b>Worse:</b> it found 1 usable team profile to Parallel's 6, because LinkedIn blocks it.
        </li>
      </Box>
    </Box>
  );
}

/** What one company costs, as a bar split by step, plus the daily and one-off costs, and the same card from an Opus agent. */
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
      <OpusComparison parallelUsd={perCompany} />
    </>
  );
}
