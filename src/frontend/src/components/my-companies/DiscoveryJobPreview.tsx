import Box from '@mui/material/Box';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type { DiscoveryJobPreview as DiscoveryJobPreviewRow } from '../../features/userCompanies/userCompaniesApi';

interface DiscoveryJobPreviewProps {
  jobs: DiscoveryJobPreviewRow[];
}

/**
 * The handful of jobs a completed discovery actually read (E7 capture pivot, D3).
 *
 * These are the rows the ACCEPTANCE REPLAY returned — the same bytes the nightly
 * harvest will read, not what the capture browser happened to see. That distinction is
 * the whole reason showing them is meaningful: "we can read this board" is a claim, and
 * these five rows are the evidence for it. It is also the fastest way for a user to
 * catch us tracking the wrong list on a site with several job-shaped feeds.
 *
 * `url` is optional by design: the backend keeps it only when it is an http(s) link
 * (a `javascript:` href harvested off a stranger's board is a stored-XSS vector), so a
 * row without one renders as plain text rather than as a dead or dangerous link.
 * Renders nothing at all for an empty list — an empty "here's what we found" box says
 * the opposite of what it means.
 */
export function DiscoveryJobPreview({ jobs }: DiscoveryJobPreviewProps) {
  if (jobs.length === 0) {
    return null;
  }
  return (
    <Box sx={{ mt: 1.5 }} data-testid="discovery-job-preview">
      <Typography variant="subtitle2" gutterBottom>
        A few of the jobs we found
      </Typography>
      <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2.5 }}>
        {jobs.map((job, index) => (
          <Typography
            component="li"
            // Titles legitimately repeat on a board ("Software Engineer" ×4) and the
            // url is optional, so neither alone is a stable key.
            key={`${index}-${job.title}`}
            variant="body2"
            sx={{ overflowWrap: 'anywhere' }}
          >
            {job.url ? (
              <Link href={job.url} target="_blank" rel="noopener noreferrer">
                {job.title}
              </Link>
            ) : (
              job.title
            )}
            {job.location ? (
              <Typography component="span" variant="body2" color="text.secondary">
                {' — '}
                {job.location}
              </Typography>
            ) : null}
          </Typography>
        ))}
      </Stack>
    </Box>
  );
}
