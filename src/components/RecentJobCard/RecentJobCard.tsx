import { Card, CardContent, Typography, Stack, Link } from '@mui/material';
import { OpenInNew } from '@mui/icons-material';
import type { Job } from '../../types';
import { useJobMetadata } from '../shared/jobCard/useJobMetadata';
import { JobChipsSection } from '../shared/jobCard/JobChipsSection';
import { CARD_HOVER_SX, CARD_VARIANT } from '../shared/jobCard/jobCardStyles';

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
  const { postedAgo } = useJobMetadata(job.createdAt);

  const handleCardClick = () => {
    window.open(job.url, '_blank', 'noopener,noreferrer');
  };

  const handleLinkedInClick = (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent card click when clicking LinkedIn button
  };

  return (
    <Card
      variant={CARD_VARIANT}
      sx={{
        mb: 2,
        cursor: 'pointer',
        ...CARD_HOVER_SX,
      }}
      onClick={handleCardClick}
    >
      <CardContent>
        {/* Company header */}
        <Typography variant="subtitle2" color="text.secondary" fontWeight="bold" mb={1}>
          {companyName}
        </Typography>

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
        <Stack sx={{ mb: 1 }}>
          <JobChipsSection
            department={job.department}
            isRemote={job.isRemote}
            classification={job.classification}
          />
        </Stack>

        {/* LinkedIn recruiter link */}
        {recruiterLinkedInUrl && (
          <Link
            href={recruiterLinkedInUrl}
            target="_blank"
            rel="noopener noreferrer"
            variant="caption"
            color="primary"
            underline="hover"
            onClick={handleLinkedInClick}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.5,
              mb: 0.5,
              cursor: 'pointer',
            }}
          >
            Find recruiter and hiring manager posts on LinkedIn
            <OpenInNew sx={{ fontSize: '0.875rem' }} />
          </Link>
        )}

        {/* Posted date */}
        <Typography variant="caption" color="text.secondary">
          Posted {postedAgo}
        </Typography>
      </CardContent>
    </Card>
  );
}
