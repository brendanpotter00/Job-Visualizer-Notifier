import { Card, CardContent, Typography, Chip, Stack, Link, Box } from '@mui/material';
import { formatDistanceToNow } from 'date-fns';
import type { Job } from '../../types';

interface JobCardProps {
  job: Job;
}

/**
 * Card component for displaying individual job posting
 */
export function JobCard({ job }: JobCardProps) {
  const postedAgo = formatDistanceToNow(new Date(job.createdAt), { addSuffix: true });

  return (
    <Card variant="outlined" sx={{ '&:hover': { bgcolor: 'action.hover' } }}>
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
            {job.department && <Chip label={job.department} size="small" variant="outlined" />}
            {job.location && <Chip label={job.location} size="small" variant="outlined" />}
            {job.isRemote && (
              <Chip label="Remote" size="small" color="primary" variant="outlined" />
            )}
            {job.employmentType && (
              <Chip label={job.employmentType} size="small" variant="outlined" />
            )}
          </Stack>

          {job.classification.isSoftwareAdjacent && (
            <Stack direction="row" spacing={1}>
              <Chip label={job.classification.category} size="small" color="primary" />
            </Stack>
          )}

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
