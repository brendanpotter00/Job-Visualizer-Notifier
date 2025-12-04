import { Card, CardContent, Typography, Chip, Stack, Link, Box } from '@mui/material';
import type { Job } from '../../../types';
import { useJobMetadata } from '../../shared/JobCard/useJobMetadata.ts';
import { JobChipsSection } from '../../shared/JobCard/JobChipsSection.tsx';
import { CARD_HOVER_SX, CARD_VARIANT } from '../../shared/JobCard/jobCardStyles.ts';

interface JobCardProps {
  job: Job;
}

/**
 * Card component for displaying individual job posting
 */
export function JobCard({ job }: JobCardProps) {
  const { postedAgo } = useJobMetadata(job.createdAt);

  return (
    <Card variant={CARD_VARIANT} sx={CARD_HOVER_SX}>
      <CardContent>
        <Stack spacing={1}>
          <Box>
            <Link
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              underline="hover"
              color="inherit"
            >
              <Typography variant="h6" component="h3">
                {job.title}
              </Typography>
            </Link>
            <Typography variant="body2" color="text.secondary">
              {postedAgo}
            </Typography>
          </Box>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {job.location && <Chip label={job.location} size="small" variant="outlined" />}
            {job.employmentType && (
              <Chip label={job.employmentType} size="small" variant="outlined" />
            )}
          </Stack>

          <JobChipsSection
            department={job.department}
            isRemote={job.isRemote}
            classification={job.classification}
          />

          {job.tags && job.tags.length > 0 && (
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {job.tags
                .filter((tag): tag is string => typeof tag === 'string' && tag.length > 0)
                .slice(0, 5)
                .map((tag, index) => (
                  <Chip key={index} label={tag} size="small" variant="filled" />
                ))}
            </Stack>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
