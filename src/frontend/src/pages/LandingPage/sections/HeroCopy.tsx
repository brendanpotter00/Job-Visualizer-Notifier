import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent, HeroVariantId } from '../content';

interface HeroCopyProps {
  content: LandingContent;
  variant: HeroVariantId;
  align?: 'left' | 'center';
  /** Render the SWE-flagship support line under the subheadline. */
  showBroadSupportLine?: boolean;
}

/**
 * The single h1 + fragment-stack subheadline (brief §4/§9). Real DOM text
 * always — this block is the page's LCP element by design, never a canvas.
 */
export function HeroCopy({
  content,
  variant,
  align = 'center',
  showBroadSupportLine = false,
}: HeroCopyProps) {
  const hero = content.heroVariants[variant];
  return (
    <Box sx={{ textAlign: align, maxWidth: 780, mx: align === 'center' ? 'auto' : 0 }}>
      <Typography
        variant="h1"
        sx={{
          fontSize: RESPONSIVE.landingProto.heroHeadlineFontSize,
          fontWeight: 600,
          letterSpacing: '-0.02em',
          lineHeight: 1.1,
        }}
      >
        {hero.headline}
      </Typography>
      <Typography
        sx={{
          fontSize: RESPONSIVE.landingProto.heroSubFontSize,
          color: 'text.secondary',
          mt: 2,
          lineHeight: 1.5,
        }}
      >
        {hero.subheadline}
      </Typography>
      {showBroadSupportLine && (
        <Typography variant="body2" sx={{ color: 'text.secondary', mt: 1.5 }}>
          {content.broadSupportLine}
        </Typography>
      )}
    </Box>
  );
}
