import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingHero } from '../content';

interface HeroCopyProps {
  hero: LandingHero;
  /** Set on the h1 so the hero `<section>` can point `aria-labelledby` at it. */
  headingId: string;
}

/**
 * The single h1, in two tones. The black half is the hook; the gray half is
 * the query phrase and the number, inside the SAME h1 so the page's one
 * heading carries both (brief §4/§9). Real DOM text always — this block is the
 * page's LCP element by design, never a canvas.
 *
 * Left-aligned and set at a regular weight on purpose: a centred bold
 * headline reads as a poster, and the page is meant to read as a document.
 */
export function HeroCopy({ hero, headingId }: HeroCopyProps) {
  return (
    <Typography
      variant="h1"
      id={headingId}
      sx={{
        fontSize: RESPONSIVE.landingProto.heroHeadlineFontSize,
        fontWeight: 500,
        letterSpacing: '-0.03em',
        lineHeight: 1.08,
        maxWidth: 1000,
      }}
    >
      {hero.headline}{' '}
      <Box component="span" sx={{ color: 'text.disabled' }}>
        {hero.continuation}
      </Box>
    </Typography>
  );
}
