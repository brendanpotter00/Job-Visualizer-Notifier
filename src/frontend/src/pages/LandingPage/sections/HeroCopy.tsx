import { Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingHero } from '../content';
import { heroRiseIn } from './heroRiseIn';

interface HeroCopyProps {
  hero: LandingHero;
  headingId: string;
}

/**
 * The single h1, one tone: "No reposts. No stale listings. No noise. Just
 * jobs." It was two tones until 2026-11-12, with a gray continuation carrying
 * the query phrase and the 130+ number; the owner cut it for "Just jobs." Real
 * DOM text always — this block is the page's LCP element by design, never a
 * canvas.
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
        textWrap: 'balance',
        ...heroRiseIn(),
      }}
    >
      {hero.headline}
    </Typography>
  );
}
