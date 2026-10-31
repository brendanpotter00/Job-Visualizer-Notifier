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
}

/**
 * Eyebrow over a short h2: the one opening every section shares. Rendering it
 * from one component is what keeps the rhythm identical down the page; a
 * section that needs a different opening is a section that needs a different
 * page.
 */
export function SectionIntro({ eyebrow, heading, headingId }: SectionIntroProps) {
  return (
    <Box sx={{ mb: RESPONSIVE.landingProto.sectionTitleMarginBottom }}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <Typography
        component="h2"
        id={headingId}
        sx={{
          fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
          fontWeight: 500,
          letterSpacing: '-0.02em',
          lineHeight: 1.15,
          mt: 1.5,
          maxWidth: 640,
        }}
      >
        {heading}
      </Typography>
    </Box>
  );
}
