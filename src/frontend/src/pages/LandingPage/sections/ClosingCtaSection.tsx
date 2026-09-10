import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';
import { CTAButtons } from './CTAButtons';

const HEADING_ID = 'landing-closing-heading';

interface ClosingCtaSectionProps {
  content: LandingContent;
}

/**
 * The last thing before the footer: one line and the same two CTAs the hero
 * opened with. Centred, unlike everything above it, so the page visibly
 * changes gear before it ends instead of trailing off into the footer links.
 */
export function ClosingCtaSection({ content }: ClosingCtaSectionProps) {
  return (
    <Box
      component="section"
      aria-labelledby={HEADING_ID}
      data-testid="closing-cta"
      sx={{ textAlign: 'center' }}
    >
      <Typography
        component="h2"
        id={HEADING_ID}
        sx={{
          fontSize: RESPONSIVE.landingProto.closingHeadingFontSize,
          fontWeight: 500,
          letterSpacing: '-0.03em',
          lineHeight: 1.1,
          mb: 4,
        }}
      >
        {content.closing.heading}
      </Typography>
      <CTAButtons ctas={content.ctas} showSecondary align="center" />
    </Box>
  );
}

export default ClosingCtaSection;
