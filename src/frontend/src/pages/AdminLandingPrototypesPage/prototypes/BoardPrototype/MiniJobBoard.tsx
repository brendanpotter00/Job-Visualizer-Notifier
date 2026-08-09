import { useMemo, useState } from 'react';
import { Box, Button, Chip, Stack } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { Job } from '../../../../types';
import { JobListingCard } from '../../../../components/shared/JobCard/JobListingCard';
import { FACET_LABELS } from '../../../../constants/enrichment';
import { ROUTES } from '../../../../config/routes';

interface MiniJobBoardProps {
  jobs: Job[];
  /** For the "Browse all N jobs" closer. */
  totalOpenJobs: number;
  maxItems?: number;
}

/**
 * The slimmed, embedded job board (interview: grepjob-inspired, WITHOUT the
 * keyword-matching feature). Real JobListingCards over mock jobs, one simple
 * category chip row — full filtering lives on the real board (brief §11 P2).
 */
export function MiniJobBoard({ jobs, totalOpenJobs, maxItems = 10 }: MiniJobBoardProps) {
  const [category, setCategory] = useState<string | null>(null);

  const categories = useMemo(() => {
    const present = new Set<string>();
    for (const job of jobs) {
      if (job.category) present.add(job.category);
    }
    return [...present].sort();
  }, [jobs]);

  const visible = useMemo(() => {
    const sorted = [...jobs].sort(
      (a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime()
    );
    const filtered = category === null ? sorted : sorted.filter((j) => j.category === category);
    return filtered.slice(0, maxItems);
  }, [jobs, category, maxItems]);

  return (
    <Box sx={{ maxWidth: 760, mx: 'auto' }}>
      <Stack direction="row" sx={{ gap: 1, flexWrap: 'wrap', mb: 2, justifyContent: 'center' }}>
        <Chip
          label="All roles"
          size="small"
          variant={category === null ? 'filled' : 'outlined'}
          onClick={() => setCategory(null)}
        />
        {categories.map((slug) => (
          <Chip
            key={slug}
            label={FACET_LABELS[slug] ?? slug}
            size="small"
            variant={category === slug ? 'filled' : 'outlined'}
            onClick={() => setCategory(category === slug ? null : slug)}
          />
        ))}
      </Stack>
      {visible.map((job) => (
        <JobListingCard key={job.id} job={job} />
      ))}
      <Box sx={{ textAlign: 'center', mt: 3 }}>
        <Button component={RouterLink} to={ROUTES.RECENT_JOBS} variant="outlined">
          Browse all {totalOpenJobs.toLocaleString()}+ jobs
        </Button>
      </Box>
    </Box>
  );
}
