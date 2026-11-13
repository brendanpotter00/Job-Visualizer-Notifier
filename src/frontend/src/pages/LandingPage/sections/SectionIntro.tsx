import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { SectionIntro as SectionIntroContent } from '../content';

interface EyebrowProps {
  children: ReactNode;
  /** `text.disabled` instead of `text.secondary`: for labelling a grayed tier. */
  muted?: boolean;
}

/**
 * The small uppercase overline every section opens with. Deliberately the
 * smallest type on the page: it names a section, it is not content to read, so
 * it must never compete with the heading under it.
 */
export function Eyebrow({ children, muted = false }: EyebrowProps) {
  return (
    <Typography
      component="p"
      sx={{
        color: muted ? 'text.disabled' : 'text.secondary',
        fontSize: RESPONSIVE.landingProto.eyebrowFontSize,
        fontWeight: 500,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        lineHeight: 1.4,
      }}
    >
      {children}
    </Typography>
  );
}

interface SectionIntroProps extends SectionIntroContent {
  /** Set on the h2 so the enclosing `<section>` can point `aria-labelledby` at it. */
  headingId: string;
  /**
   * Put the h2 above the eyebrow instead of under it. Only the LinkedIn
   * comparison sets it (owner decision, 2026-11-12): its heading is the claim
   * and "Why not LinkedIn" reads as the caption under it.
   */
  headingFirst?: boolean;
}

/** Air between the eyebrow and the h2, whichever comes first. */
const INTRO_GAP = 1.5;

/**
 * Eyebrow over a short h2: the one opening every section shares. Rendering it
 * from one component is what keeps the rhythm identical down the page — the
 * one sanctioned variation is `headingFirst`, which swaps the order and keeps
 * the same type, gap and bottom margin.
 */
export function SectionIntro({
  eyebrow,
  heading,
  headingId,
  headingFirst = false,
}: SectionIntroProps) {
  const title = (
    <Typography
      component="h2"
      id={headingId}
      sx={{
        fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
        fontWeight: 500,
        letterSpacing: '-0.02em',
        lineHeight: 1.15,
        mt: headingFirst ? 0 : INTRO_GAP,
        maxWidth: 640,
      }}
    >
      {heading}
    </Typography>
  );
  return (
    <Box sx={{ mb: RESPONSIVE.landingProto.sectionTitleMarginBottom }}>
      {headingFirst ? (
        <>
          {title}
          <Box sx={{ mt: INTRO_GAP }}>
            <Eyebrow>{eyebrow}</Eyebrow>
          </Box>
        </>
      ) : (
        <>
          <Eyebrow>{eyebrow}</Eyebrow>
          {title}
        </>
      )}
    </Box>
  );
}
