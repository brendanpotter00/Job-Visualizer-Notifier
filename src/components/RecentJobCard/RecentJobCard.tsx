import { Card, CardContent, Typography, IconButton, Chip, Stack, Box } from '@mui/material';
import { LinkedIn as LinkedInIcon } from '@mui/icons-material';
import { formatDistanceToNow } from 'date-fns';
import type { Job } from '../../types';

interface RecentJobCardProps {
  job: Job;
  companyName: string;
  recruiterLinkedInUrl?: string;
}

/**
 * Job card for Recent Job Postings page
 * Displays company name header and optional LinkedIn recruiter link
 * Entire card is clickable to view job posting
 */
export function RecentJobCard({ job, companyName, recruiterLinkedInUrl }: RecentJobCardProps) {
  const postedAgo = formatDistanceToNow(new Date(job.createdAt), { addSuffix: true });

  const handleCardClick = () => {
    window.open(job.url, '_blank', 'noopener,noreferrer');
  };

  const handleLinkedInClick = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent card click when clicking LinkedIn button
  };

  return (
    <Card
      variant="outlined"
      sx={{
        mb: 2,
        cursor: 'pointer',
        '&:hover': { bgcolor: 'action.hover' },
      }}
      onClick={handleCardClick}
    >
      <CardContent>
        {/* Company header with LinkedIn button */}
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
          <Typography variant="subtitle2" color="text.secondary" fontWeight="bold">
            {companyName}
          </Typography>
          {recruiterLinkedInUrl && (
            <IconButton
              size="small"
              href={recruiterLinkedInUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="View LinkedIn recruiters"
              sx={{ color: 'primary.main' }}
              onClick={handleLinkedInClick}
            >
              <LinkedInIcon fontSize="small" />
            </IconButton>
          )}
        </Box>

        {/* Job title */}
        <Typography variant="h6" component="h3" gutterBottom>
          {job.title}
        </Typography>

        {/* Location and employment type */}
        <Typography variant="body2" color="text.secondary" gutterBottom>
          {job.location && job.employmentType
            ? `${job.location} · ${job.employmentType}`
            : job.location || job.employmentType || 'Location not specified'}
        </Typography>

        {/* Chips for metadata */}
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
          {job.department && <Chip label={job.department} size="small" variant="outlined" />}
          {job.isRemote && (
            <Chip label="Remote" size="small" color="primary" variant="outlined" />
          )}
          {job.classification.isSoftwareAdjacent && (
            <Chip label={job.classification.category} size="small" color="primary" />
          )}
        </Stack>

        {/* Posted date */}
        <Typography variant="caption" color="text.secondary">
          Posted {postedAgo}
        </Typography>
      </CardContent>
    </Card>
  );
}
