import { Box, Divider, Link, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { LandingContent } from '../content';

interface FooterLiteProps {
  content: LandingContent;
}

/**
 * Minimal landing footer: the closing fragment-stack tagline (brief §11 —
 * proof closes the page), nav links, and the query-shaped "popular searches"
 * stubs (brief §9 — the 11.3 internal-linking surface, rendered as a pattern
 * now; every target points at the board until real category pages exist).
 */
export function FooterLite({ content }: FooterLiteProps) {
  return (
    <Box component="footer" sx={{ pb: 8 }}>
      <Divider sx={{ mb: 6 }} />
      <Typography sx={{ fontWeight: 600, textAlign: 'center', mb: 4, lineHeight: 1.7 }}>
        {content.footer.tagline}
      </Typography>
      <Box sx={{ display: 'flex', gap: 3, justifyContent: 'center', flexWrap: 'wrap', mb: 6 }}>
        {content.footer.links.map((link) => (
          <Link
            key={link.label}
            component={RouterLink}
            to={link.to}
            variant="body2"
            sx={{ color: 'text.secondary' }}
          >
            {link.label}
          </Link>
        ))}
      </Box>
      <Typography
        variant="overline"
        component="h2"
        sx={{ display: 'block', textAlign: 'center', color: 'text.secondary' }}
      >
        Popular searches
      </Typography>
      <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap', mt: 2 }}>
        {content.popularSearches.map((search) => (
          <Link
            key={search.label}
            component={RouterLink}
            to={search.to}
            variant="caption"
            sx={{ color: 'text.secondary' }}
          >
            {search.label}
          </Link>
        ))}
      </Box>
      <Typography
        variant="caption"
        sx={{ display: 'block', textAlign: 'center', color: 'text.disabled', mt: 6 }}
      >
        {content.categoryLine}
      </Typography>
    </Box>
  );
}
