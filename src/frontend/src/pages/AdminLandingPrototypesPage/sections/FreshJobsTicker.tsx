import { useMemo } from 'react';
import { Box, Chip, Typography } from '@mui/material';
import { formatDistanceStrict } from 'date-fns';
import type { Job } from '../../../types';
import { CompanyLogo } from '../../../components/shared/CompanyLogo/CompanyLogo';
import { RESPONSIVE } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { TOP_COMPANY_IDS } from '../content';
import { selectTickerJobs } from './tickerJobs';

interface FreshJobsTickerProps {
  jobs: Job[];
  /** The fixtures' MOCK_NOW — see LandingPrototypeProps.now. */
  now: number;
  maxItems?: number;
}

/**
 * The "recently posted at top companies" rail (interview Q1/Q6). Rich data →
 * an auto-drifting marquee of pills; sparse data (weekend reality, brief §8) →
 * a static wrapped row honestly labeled "Fresh this week". The posted-ago label
 * is the loudest element on each pill — the timestamp IS the pitch (brief §11).
 */
export function FreshJobsTicker({ jobs, now, maxItems = 10 }: FreshJobsTickerProps) {
  const isMobile = useIsMobile();
  const logoSize = isMobile
    ? RESPONSIVE.landingProto.tickerLogoSize.compact
    : RESPONSIVE.landingProto.tickerLogoSize.default;

  const { items, mode } = useMemo(
    () => selectTickerJobs(jobs, TOP_COMPANY_IDS, now, maxItems),
    [jobs, now, maxItems]
  );
  if (items.length === 0) return null;

  const pills = items.map((job) => (
    <Chip
      key={job.id}
      component="a"
      href={job.url}
      clickable
      icon={<CompanyLogo companyId={job.company} size={logoSize} decorative />}
      label={
        <Box component="span" sx={{ display: 'inline-flex', alignItems: 'baseline', gap: 0.75 }}>
          <Typography component="span" variant="body2" sx={{ fontWeight: 600 }}>
            {formatDistanceStrict(new Date(job.firstSeenAt), new Date(now))} ago
          </Typography>
          <Typography component="span" variant="body2" sx={{ color: 'text.secondary' }}>
            {job.title}
          </Typography>
        </Box>
      }
      sx={{ height: 'auto', py: 0.5, '& .MuiChip-label': { py: 0.25 } }}
    />
  ));

  return (
    <Box>
      <Typography
        variant="overline"
        component="h2"
        sx={{ display: 'block', textAlign: 'center', color: 'text.secondary', mb: 1 }}
      >
        {mode === 'fresh' ? 'Posted in the last 48 hours' : 'Fresh this week'}
      </Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, justifyContent: 'center' }}>
        {pills}
      </Box>
    </Box>
  );
}
