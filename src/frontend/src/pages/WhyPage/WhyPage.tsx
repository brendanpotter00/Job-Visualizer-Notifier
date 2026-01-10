import { useMemo } from 'react';
import { Container, Box, Typography, List, ListItem, Link, Paper, Grid } from '@mui/material';
import type { Company } from '../../types';
import { COMPANIES } from '../../config/companies';
import { OpenInNew } from '@mui/icons-material';

/**
 * WhyPage - Explains the purpose of this application and displays supported companies
 *
 * Features:
 * - Introduction text explaining why this was built
 * - Lists all supported companies grouped by ATS provider
 * - Each company links to its job board
 *
 * @returns Why This Was Built page component
 */
export function WhyPage() {
  // Display-friendly names for ATS types
  const atsDisplayNames: Record<string, string> = {
    'backend-scraper': 'Custom Scrapers',
  };

  // Coming soon companies for custom scrapers
  const comingSoonScrapers = [
    { name: 'Apple', jobsUrl: 'https://jobs.apple.com/' },
    { name: 'Netflix', jobsUrl: 'https://jobs.netflix.com/' },
  ];

  // Group companies by ATS type for organized display
  const companiesByATS = useMemo(() => {
    const grouped: Record<string, Company[]> = {};
    for (const company of COMPANIES) {
      if (!grouped[company.ats]) {
        grouped[company.ats] = [];
      }
      grouped[company.ats].push(company);
    }
    return grouped;
  }, []);

  return (
    <Container maxWidth={false} sx={{ px: { xs: 2, sm: 3, md: 4 } }}>
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Why This Was Built
        </Typography>

        {/* Introduction section */}
        <Paper sx={{ p: 3, mb: 4 }}>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            I made this platform because the best way to get job interviews is to apply early. Other
            job platforms are bloated with random companies and stale job listings that were really
            posted weeks ago.
          </Typography>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            So I created this platform. It pulls directly from the company's job postings and top
            companies. No more shifting through no-name companies or wondering if the job listing is
            actually new.
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
              <strong>Reach out to recruiters and hiring managers via the LinkedIn links</strong>
            </Typography>
            <Typography component="li" variant="body1">
              <strong>Apply early</strong>
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
        <Typography variant="h3" component="h1" gutterBottom>
          Future Plans
        </Typography>

        <Paper sx={{ p: 3, mb: 4 }}>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            I am planning on adding:
          </Typography>
          <Box component="ul" sx={{ mt: 0, mb: 0, pl: 3 }}>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Notification System
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Company-Website Web Scrapers (Apple, Google, Microsoft, Meta, etc)
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              AI Powered Resume to Job Listing Matching
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Accounts
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Saved Filter Settings
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Historical Data
            </Typography>
          </Box>
        </Paper>

        {/* Supported Companies section */}
        <Typography variant="h4" component="h2" gutterBottom sx={{ mt: 4 }}>
          Supported Companies
        </Typography>

        <Typography variant="body2" component="p" color="text.secondary" sx={{ mb: 2 }}>
          We currently track {COMPANIES.length} companies across{' '}
          {Object.keys(companiesByATS).length} different ATS platforms.
        </Typography>

        {/* Group companies by ATS */}
        <Grid container spacing={3}>
          {Object.entries(companiesByATS).map(([ats, companies]) => (
            <Grid key={ats} size={{ xs: 12, sm: 6, md: 'grow' }}>
              <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <Typography
                  variant="h6"
                  component="h3"
                  sx={{
                    textTransform: atsDisplayNames[ats] ? 'none' : 'capitalize',
                    mb: 1,
                    color: 'primary.main',
                  }}
                >
                  {atsDisplayNames[ats] || ats} ({companies.length})
                </Typography>
                <Paper variant="outlined" sx={{ p: 2, flexGrow: 1 }}>
                  <List dense disablePadding>
                    {companies.map((company) => (
                      <ListItem key={company.id} sx={{ py: 0.5, px: 0 }}>
                        <Link
                          href={company.jobsUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          underline="hover"
                          sx={{ fontWeight: 500, fontSize: '1rem' }}
                        >
                          {company.name}
                        </Link>
                      </ListItem>
                    ))}
                    {ats === 'backend-scraper' &&
                      comingSoonScrapers.map((company) => (
                        <ListItem key={company.name} sx={{ py: 0.5, px: 0 }}>
                          <Typography
                            component="span"
                            sx={{ fontWeight: 500, fontSize: '1rem', color: 'text.secondary' }}
                          >
                            {company.name}{' '}
                            <Typography
                              component="span"
                              sx={{ fontSize: '0.75rem', fontStyle: 'italic' }}
                            >
                              (Coming Soon)
                            </Typography>
                          </Typography>
                        </ListItem>
                      ))}
                  </List>
                </Paper>
              </Box>
            </Grid>
          ))}
        </Grid>
      </Box>
    </Container>
  );
}
