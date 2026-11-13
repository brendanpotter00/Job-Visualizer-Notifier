import { Container, Box, Typography, Link, Paper } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import OpenInNew from '@mui/icons-material/OpenInNew';
import { RESPONSIVE } from '../../config/responsive';

/** Shared styling for Paper sections */
const sectionPaperSx: SxProps<Theme> = { p: RESPONSIVE.spacing.paperPadding, mb: 4 };

/**
 * WhyPage - Explains the purpose of this application
 *
 * @returns Why This Was Built page component
 */
export function WhyPage() {
  return (
    <Container maxWidth={false} sx={{ px: { xs: 2, sm: 3, md: 4 } }}>
      <Box sx={{ my: RESPONSIVE.spacing.pageMarginY }}>
        <Typography
          variant="h3"
          component="h1"
          gutterBottom
          sx={{ fontSize: RESPONSIVE.fontSize.pageTitle }}
        >
          Why This Was Built
        </Typography>

        {/* Introduction section */}
        <Paper sx={sectionPaperSx}>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            I made this platform because the best way to get job interviews is to apply early. Other
            job platforms are bloated with random companies and stale job listings that were really
            posted weeks ago.
          </Typography>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            So I created this platform. It pulls directly from top companies' job postings. No more
            shifting through no-name companies or wondering if the job listing is actually new.
          </Typography>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            The best way to get interviews is to either apply earlier or reach out to the hiring
            manager or recruiters, especially in this job market.
          </Typography>
          <Typography variant="body1" component="p" sx={{ mb: 1, fontWeight: 600 }}>
            To use this website:
          </Typography>
          <Box component="ol" sx={{ mt: 0, mb: 2, pl: 3 }}>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              <strong>Set the time window filters to less than 24 hrs</strong>
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              <strong>Check the website frequently</strong>
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              <strong>Apply early</strong>
            </Typography>
            <Typography component="li" variant="body1">
              <strong>Reach out to recruiters and hiring managers via the LinkedIn links</strong>
            </Typography>
          </Box>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            Feel free to reach out to me to suggest new companies, features, or give any other
            feedback.
          </Typography>
          <Link
            href="https://www.linkedin.com/in/brendan-potter00/"
            target="_blank"
            rel="noopener noreferrer"
            sx={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 0.5,
              color: 'primary.main',
              '&:hover': {
                textDecoration: 'underline',
              },
            }}
          >
            Reach out to Brendan Potter <OpenInNew sx={{ fontSize: '1rem' }} />
          </Link>
        </Paper>
      </Box>
    </Container>
  );
}
