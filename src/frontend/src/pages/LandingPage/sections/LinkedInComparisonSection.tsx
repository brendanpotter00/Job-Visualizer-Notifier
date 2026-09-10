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

/**
 * Off-screen but still in the accessibility tree — the standard clip recipe.
 * `display: none` would drop the text for assistive tech too, which is the one
 * thing this must not do.
 */
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
  /** The column this cell belongs to. */
  column: string;
  /** LinkedIn's cell is the quieter one: the contrast is the point of the row. */
  muted?: boolean;
  children: ReactNode;
}

/**
 * One cell, always prefixed with its column name so it is never an
 * unattributed paragraph. On a phone the prefix is visible (there is no head
 * row); from `sm` up the head row shows the names and the prefix goes
 * visually hidden — hidden, not removed, so a screen reader on desktop still
 * hears "LinkedIn:" / "onesecondswe:" before every cell. The head row itself
 * is decorative for exactly that reason.
 */
function ComparisonCell({ column, muted = false, children }: ComparisonCellProps) {
  return (
    <Typography
      component="p"
      sx={{
        position: 'relative',
        minWidth: 0,
        fontSize: RESPONSIVE.landingProto.bodyFontSize,
        lineHeight: 1.6,
        color: muted ? 'text.secondary' : 'text.primary',
        fontWeight: muted ? 400 : 500,
      }}
    >
      <Box
        component="span"
        sx={(theme) => ({
          color: 'text.disabled',
          fontWeight: 400,
          [theme.breakpoints.up('sm')]: VISUALLY_HIDDEN,
        })}
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

      {/* Decorative: every cell already carries its column name (visually
          hidden from `sm` up), so announcing the head row would say each name
          twice. */}
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
