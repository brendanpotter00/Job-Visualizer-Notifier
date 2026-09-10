import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';
import { Eyebrow, SectionIntro } from './SectionIntro';

const HEADING_ID = 'landing-comparison-heading';

/**
 * Three tracks from `sm` up: the row label, LinkedIn, onesecondswe. On a
 * phone the three stack, and each cell names its own column instead (see
 * `ComparisonCell`), so the column-head row is desktop-only.
 */
const ROW_SX = {
  display: 'grid',
  gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: '9rem minmax(0, 1fr) minmax(0, 1fr)' },
  columnGap: { xs: 0, sm: 4 },
  rowGap: 1,
} as const;

interface ComparisonCellProps {
  /** The column this cell belongs to; spoken on phones, where there is no head row. */
  column: string;
  /** LinkedIn's cell is the quieter one: the contrast is the point of the row. */
  muted?: boolean;
  children: ReactNode;
}

function ComparisonCell({ column, muted = false, children }: ComparisonCellProps) {
  return (
    <Typography
      component="p"
      sx={{
        minWidth: 0,
        fontSize: RESPONSIVE.landingProto.bodyFontSize,
        lineHeight: 1.6,
        color: muted ? 'text.secondary' : 'text.primary',
        fontWeight: muted ? 400 : 500,
      }}
    >
      <Box
        component="span"
        sx={{
          display: { xs: 'inline', sm: 'none' },
          color: 'text.disabled',
          fontWeight: 400,
        }}
      >
        {column}:{' '}
      </Box>
      {children}
    </Typography>
  );
}

interface LinkedInComparisonSectionProps {
  content: LandingContent;
}

/**
 * The LinkedIn comparison (owner-directed 2026-09-10). Four ruled rows, each a
 * checkable product fact on the left and what onesecondswe does instead on the
 * right. No verdict column, no ticks and crosses: the rows are facts and the
 * reader draws the conclusion, which is the only comparison framing that
 * survives being quoted by an answer engine (brief §10 P4).
 */
export function LinkedInComparisonSection({ content }: LinkedInComparisonSectionProps) {
  const { eyebrow, heading, columns, rows } = content.comparison;

  return (
    <Box component="section" aria-labelledby={HEADING_ID} data-testid="linkedin-comparison">
      <SectionIntro eyebrow={eyebrow} heading={heading} headingId={HEADING_ID} />

      <Box sx={{ ...ROW_SX, display: { xs: 'none', sm: 'grid' }, pb: 1.5 }} aria-hidden>
        <Box />
        <Eyebrow>{columns.linkedin}</Eyebrow>
        <Eyebrow>{columns.onesecondswe}</Eyebrow>
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
            sx={{ fontSize: RESPONSIVE.landingProto.blockTitleFontSize, fontWeight: 500 }}
          >
            {row.label}
          </Typography>
          <ComparisonCell column={columns.linkedin} muted>
            {row.linkedin}
          </ComparisonCell>
          <ComparisonCell column={columns.onesecondswe}>{row.onesecondswe}</ComparisonCell>
        </Box>
      ))}
    </Box>
  );
}

export default LinkedInComparisonSection;
