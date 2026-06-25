import { useMemo } from 'react';
import { Container, Box, Typography, List, ListItem, Link, Paper, Grid } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { Company } from '../../types';
import { COMPANIES, COMING_SOON_SCRAPERS } from '../../config/companies';
import { ROUTES } from '../../config/routes';
import { COMPANY_PARAM } from '../../lib/url';
import { OpenInNew, CheckCircle } from '@mui/icons-material';
import {
  ATS_DISPLAY_NAMES,
  NON_CAPITALIZED_GROUPS,
  getATSGroupKey,
  type ATSGroupKey,
} from '../../config/atsSource';
import { RESPONSIVE } from '../../config/responsive';

/** Shared styling for Paper sections */
const sectionPaperSx: SxProps<Theme> = { p: RESPONSIVE.spacing.paperPadding, mb: 4 };

/** Inline "shipped" badge used to mark roadmap items that are already live. */
function LiveMarker() {
  return (
    <Typography
      component="span"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 0.25,
        fontSize: '0.75rem',
        fontWeight: 600,
        color: 'success.main',
        whiteSpace: 'nowrap',
      }}
    >
      <CheckCircle sx={{ fontSize: '0.9rem' }} /> Live
    </Typography>
  );
}

/**
 * WhyPage - Explains the purpose of this application and displays supported companies
 *
 * Features:
 * - Introduction text explaining why this was built
 * - Lists all supported companies grouped by ATS provider
 * - Each company links to its in-app hiring trends page
 *
 * @returns Why This Was Built page component
 */
export function WhyPage() {
  // Group companies by ATS type for organized display
  const companiesByATS = useMemo(() => {
    const grouped: Partial<Record<ATSGroupKey, Company[]>> = {};
    for (const company of COMPANIES) {
      const key = getATSGroupKey(company);
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key]!.push(company);
    }
    return grouped;
  }, []);

  // Each custom scraper is its own platform; other ATS types (including
  // Greenhouse) count once per type.
  const atsPlatformCount = Object.entries(companiesByATS).reduce(
    (total, [ats, companies]) => total + (ats === 'backend-scraper' ? companies!.length : 1),
    0
  );

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
        <Typography
          variant="h3"
          component="h1"
          gutterBottom
          sx={{ fontSize: RESPONSIVE.fontSize.pageTitle }}
        >
          Future Plans
        </Typography>

        <Paper sx={sectionPaperSx}>
          <Typography variant="body1" component="p" sx={{ mb: 2 }}>
            Progress and what's next:
          </Typography>
          <Box component="ul" sx={{ mt: 0, mb: 0, pl: 3 }}>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Accounts <LiveMarker />
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Saved Filter Settings
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Normalizing Locations with NLP <LiveMarker />
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Historical Data <LiveMarker />
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Notification System
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              AI Powered Resume To Job Listing Matching
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Company-Website Web Scrapers (Google, Apple, Microsoft) <LiveMarker />
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Custom Dashboards
            </Typography>
            <Typography component="li" variant="body1" sx={{ mb: 1 }}>
              Market Summary Page
            </Typography>
          </Box>
        </Paper>

        {/* Supported Companies section */}
        <Typography variant="h4" component="h2" gutterBottom sx={{ mt: 4 }}>
          Supported Companies
        </Typography>

        <Typography variant="body2" component="p" color="text.secondary" sx={{ mb: 2 }}>
          We currently track {COMPANIES.length} companies across {atsPlatformCount} different ATS
          platforms.
        </Typography>

        {/* Group companies by ATS */}
        <Grid container spacing={3}>
          {(Object.entries(companiesByATS) as [ATSGroupKey, Company[]][]).map(
            ([ats, companies]) => {
              const displayName = ATS_DISPLAY_NAMES[ats];
              const shouldCapitalize = !NON_CAPITALIZED_GROUPS.has(ats);

              return (
                <Grid key={ats} size={{ xs: 12, sm: 6, md: 'grow' }}>
                  <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                    <Typography
                      variant="h6"
                      component="h3"
                      sx={{
                        textTransform: shouldCapitalize ? 'capitalize' : 'none',
                        mb: 1,
                        color: 'primary.main',
                      }}
                    >
                      {displayName} ({companies.length})
                    </Typography>
                    <Paper variant="outlined" sx={{ p: 2, flexGrow: 1 }}>
                      <List dense disablePadding>
                        {companies.map((company) => (
                          <ListItem key={company.id} sx={{ py: 0.5, px: 0 }}>
                            <Link
                              component={RouterLink}
                              to={`${ROUTES.COMPANIES}?${COMPANY_PARAM}=${company.id}`}
                              underline="hover"
                              sx={{ fontWeight: 500, fontSize: '1rem' }}
                            >
                              {company.name}
                            </Link>
                          </ListItem>
                        ))}
                        {ats === 'backend-scraper' &&
                          COMING_SOON_SCRAPERS.map((company) => (
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
              );
            }
          )}
        </Grid>
      </Box>
    </Container>
  );
}
