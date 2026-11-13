import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { SectionIntro as SectionIntroContent } from '../content';

interface EyebrowProps {
  children: ReactNode;
  muted?: boolean;
}

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
  headingId: string;
}

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
