import { Box, Typography, Link as MuiLink, Stack } from '@mui/material';

interface LinksRowProps {
  jobsUrl?: string;
  recruiterLinkedInUrl?: string;
}

/**
 * Pure presentational component for displaying job posting and LinkedIn recruiter links
 */
export function LinksRow({ jobsUrl, recruiterLinkedInUrl }: LinksRowProps) {
  return (
    // Always a horizontal 2-up row — the two links sit side by side even on
    // mobile (was a column on xs). Each side keeps `flex: 1`, so they split the
    // width; spacing tightens on mobile but sm restates the current 3 (24px).
    <Stack direction="row" spacing={{ xs: 2, sm: 3 }}>
      {/* Job Postings Website Link */}
      <Box sx={{ flex: 1 }}>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Official Job Postings
        </Typography>
        {jobsUrl ? (
          <MuiLink
            href={jobsUrl}
            target="_blank"
            rel="noopener noreferrer"
            variant="body1"
            sx={{ fontWeight: 500 }}
          >
            View All Openings
          </MuiLink>
        ) : (
          <Typography variant="body1" color="text.disabled">
            URL not configured
          </Typography>
        )}
      </Box>

      {/* LinkedIn Recruiter Link */}
      <Box sx={{ flex: 1 }}>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Find Recruiters
        </Typography>
        {recruiterLinkedInUrl ? (
          <MuiLink
            href={recruiterLinkedInUrl}
            target="_blank"
            rel="noopener noreferrer"
            variant="body1"
            sx={{ fontWeight: 500 }}
          >
            LinkedIn Search
          </MuiLink>
        ) : (
          <Typography variant="body1" color="text.disabled">
            URL not configured
          </Typography>
        )}
      </Box>
    </Stack>
  );
}
