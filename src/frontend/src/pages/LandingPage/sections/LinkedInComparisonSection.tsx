import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';
import { Eyebrow, SectionIntro } from './SectionIntro';

const HEADING_ID = 'landing-comparison-heading';

const ROW_SX = {
  display: 'grid',
  gridTemplateColumns: {
    xs: 'minmax(0, 1fr) minmax(0, 1fr)',
    sm: '9rem minmax(0, 1fr) minmax(0, 1fr)',
  },
  columnGap: RESPONSIVE.landingProto.comparisonColumnGap,
  rowGap: { xs: 0.75, sm: 1 },
} as const;

const VISUALLY_HIDDEN = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  padding: 0,
  margin: '-1px',
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const;

interface ComparisonCellProps {
  column: string;
  muted?: boolean;
  children: ReactNode;
}

function ComparisonCell({ column, muted = false, children }: ComparisonCellProps) {
  return (
    <Typography
      component="p"
      sx={{
        position: 'relative',
        minWidth: 0,
        fontSize: RESPONSIVE.landingProto.comparisonCellFontSize,
        lineHeight: { xs: 1.55, sm: 1.6 },
        color: muted ? 'text.secondary' : 'text.primary',
        fontWeight: muted ? 400 : { xs: 400, sm: 500 },
      }}
    >
      <Box component="span" sx={VISUALLY_HIDDEN}>
        {column}:{' '}
      </Box>
      {children}
    </Typography>
  );
}

interface LinkedInComparisonSectionProps {
  content: LandingContent;
}

export function LinkedInComparisonSection({ content }: LinkedInComparisonSectionProps) {
  const { heading, columns, rows } = content.comparison;

  return (
    <Box component="section" aria-labelledby={HEADING_ID} data-testid="linkedin-comparison">
      <SectionIntro heading={heading} headingId={HEADING_ID} />

      <Box
        aria-hidden
        data-testid="comparison-head-compact"
        sx={{ ...ROW_SX, display: { xs: 'grid', sm: 'none' }, alignItems: 'center', pb: 1.5 }}
      >
        <Typography
          sx={{
            minWidth: 0,
            color: 'text.primary',
            fontWeight: 600,
            fontSize: RESPONSIVE.landingProto.comparisonCellFontSize,
          }}
        >
          {columns.onesecondswe}
        </Typography>
        <Typography
          sx={{ color: 'text.secondary', fontSize: RESPONSIVE.landingProto.comparisonCellFontSize }}
        >
          {columns.linkedin}
        </Typography>
      </Box>
      <Box sx={{ ...ROW_SX, display: { xs: 'none', sm: 'grid' }, pb: 1.5 }} aria-hidden>
        <Box />
        <Eyebrow>{columns.onesecondswe}</Eyebrow>
        <Eyebrow>{columns.linkedin}</Eyebrow>
      </Box>

      {rows.map((row) => (
        <Box
          key={row.id}
          data-testid={`comparison-row-${row.id}`}
          sx={{
            ...ROW_SX,
            borderTop: '1px solid',
            borderColor: 'divider',
            py: RESPONSIVE.landingProto.comparisonRowPaddingY,
          }}
        >
          <Typography
            component="h3"
            sx={{
              fontSize: RESPONSIVE.landingProto.comparisonRowLabelFontSize,
              fontWeight: { xs: 600, sm: 500 },
              gridColumn: { xs: '1 / -1', sm: 'auto' },
            }}
          >
            {row.label}
          </Typography>
          <ComparisonCell column={columns.onesecondswe}>{row.onesecondswe}</ComparisonCell>
          <ComparisonCell column={columns.linkedin} muted>
            {row.linkedin}
          </ComparisonCell>
        </Box>
      ))}
    </Box>
  );
}

export default LinkedInComparisonSection;
