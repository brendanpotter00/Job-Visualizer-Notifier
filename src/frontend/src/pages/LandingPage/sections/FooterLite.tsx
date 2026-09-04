import { Box, Divider, Link, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { LandingContent } from '../content';

interface FooterLiteProps {
  content: LandingContent;
}

/**
 * Minimal landing footer: a rule, the nav links, and the one-line category
 * description that closes the page.
 *
 * Two blocks were cut on 2026-09-03 (owner-directed). The closing proof tagline
 * ("130+ companies. ~45 min median. Zero reposts.") restated numbers the hero,
 * the claims and the feature matrix had each already made, so it landed as a
 * fourth repetition rather than as proof. The query-shaped "popular searches"
 * stubs (brief §9) were a placeholder for an internal-linking surface whose
 * targets do not exist yet — all six pointed at the same board, which is a
 * pattern demo, not navigation. Both come back when they have something new to
 * say; the stubs specifically belong with 11.3's real category pages.
 */
export function FooterLite({ content }: FooterLiteProps) {
  return (
    <Box component="footer" sx={{ pb: 8 }}>
      <Divider sx={{ mb: 6 }} />
      <Box sx={{ display: 'flex', gap: 3, justifyContent: 'center', flexWrap: 'wrap' }}>
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
        variant="caption"
        sx={{ display: 'block', textAlign: 'center', color: 'text.disabled', mt: 6 }}
      >
        {content.categoryLine}
      </Typography>
    </Box>
  );
}
