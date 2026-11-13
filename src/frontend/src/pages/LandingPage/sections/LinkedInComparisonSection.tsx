import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';
import { Eyebrow, SectionIntro } from './SectionIntro';

const HEADING_ID = 'landing-comparison-heading';

/**
 * Three tracks from `sm` up: the row label, onesecondswe, LinkedIn — ours
 * first (owner-directed 2026-11-12; it was LinkedIn first).
 *
 * On a phone (2026-11-12 mobile redesign) the two facts still sit side by
 * side, under a row label that spans both columns, and ONE column-head row at
 * the top names them. It replaced a stack of three lines per row in which every
 * cell carried a visible "LinkedIn:" / "onesecondswe:" prefix — eight
 * repetitions of two names, which read as a form rather than a comparison.
 */
const ROW_SX = {
  display: 'grid',
  gridTemplateColumns: {
    xs: 'minmax(0, 1fr) minmax(0, 1fr)',
    sm: '9rem minmax(0, 1fr) minmax(0, 1fr)',
  },
  columnGap: RESPONSIVE.landingProto.comparisonColumnGap,
  // Phone: label and facts sit closer than rows sit to each other, so each
  // label groups with its own two facts.
  rowGap: { xs: 0.75, sm: 1 },
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
 * unattributed paragraph. The prefix is visually hidden at every width (the
 * head row shows the names) — hidden, not removed, so a screen reader still
 * hears "LinkedIn:" / "onesecondswe:" before every cell. The head rows are
 * decorative for exactly that reason.
 */
function ComparisonCell({ column, muted = false, children }: ComparisonCellProps) {
  return (
    <Typography
      component="p"
      sx={{
        position: 'relative',
        minWidth: 0,
        fontSize: RESPONSIVE.landingProto.comparisonCellFontSize,
        // Slightly tighter on a phone's narrow columns; desktop keeps 1.6.
        lineHeight: { xs: 1.55, sm: 1.6 },
        color: muted ? 'text.secondary' : 'text.primary',
        // Phone: regular weight, so the row label above is the only heavy
        // text in the row and reads as its heading. Desktop keeps 500.
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

/**
 * The LinkedIn comparison (owner-directed 2026-09-10). Four ruled rows, each
 * what onesecondswe does first and the checkable LinkedIn fact it answers
 * beside it (ours-first since 2026-11-12). No verdict column, no ticks and crosses: the rows are facts and the
 * reader draws the conclusion, which is the only comparison framing that
 * survives being quoted by an answer engine (brief §10 P4).
 */
export function LinkedInComparisonSection({ content }: LinkedInComparisonSectionProps) {
  const { heading, columns, rows } = content.comparison;

  return (
    <Box component="section" aria-labelledby={HEADING_ID} data-testid="linkedin-comparison">
      <SectionIntro heading={heading} headingId={HEADING_ID} />

      {/* Decorative: every cell already carries its column name (visually
          hidden), so announcing a head row would say each name twice. */}
      {/* Phone head: sentence case, our column in the heavier weight. (The
          "1s" mark briefly led it; removed 2026-11-12, owner-directed.) */}
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
      {/* Desktop head. */}
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
              // Phone: the heaviest, largest text in the row, spanning both
              // fact columns above them — it must read as their heading.
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
