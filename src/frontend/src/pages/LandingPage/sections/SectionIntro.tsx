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
 * A small uppercase label: the comparison's column heads and the feature
 * matrix's "Coming soon" tier. Deliberately the smallest type on the page — it
 * names a thing, it is not content to read. (It no longer opens sections; see
 * SectionIntro.)
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
}

/**
 * The short h2 every section opens with. Rendering it from one component is
 * what keeps the rhythm identical down the page.
 *
 * There is no eyebrow over it any more: the small uppercase overline every
 * section used to carry was cut on 2026-11-12 (owner-directed). `Eyebrow`
 * above survives only as a label for content — the comparison's column heads
 * and the feature matrix's "Coming soon" tier.
 */
export function SectionIntro({ heading, headingId }: SectionIntroProps) {
  return (
    <Box sx={{ mb: RESPONSIVE.landingProto.sectionTitleMarginBottom }}>
      <Typography
        component="h2"
        id={headingId}
        sx={{
          fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
          fontWeight: 500,
          letterSpacing: '-0.02em',
          lineHeight: 1.15,
          maxWidth: 640,
        }}
      >
        {heading}
      </Typography>
    </Box>
  );
}
