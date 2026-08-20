import type { ComponentType } from 'react';
import { Box, Link, Typography } from '@mui/material';
import type { SvgIconProps } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import ApartmentOutlinedIcon from '@mui/icons-material/ApartmentOutlined';
import FilterListOutlinedIcon from '@mui/icons-material/FilterListOutlined';
import LanguageOutlinedIcon from '@mui/icons-material/LanguageOutlined';
import LockOpenOutlinedIcon from '@mui/icons-material/LockOpenOutlined';
import NotificationsNoneOutlinedIcon from '@mui/icons-material/NotificationsNoneOutlined';
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined';
import SellOutlinedIcon from '@mui/icons-material/SellOutlined';
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined';
import TravelExploreOutlinedIcon from '@mui/icons-material/TravelExploreOutlined';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent, LandingFeature } from '../content';

/**
 * Icon per feature id, across both tiers. Icons are presentation, not copy, so
 * the mapping lives here rather than in `content.ts`. Outlined variants only,
 * inheriting the text colour — a coloured icon set would fight the monochrome
 * page harder than the physics hero does, and an icon that kept its colour in
 * the grayed tier would break that tier's single "everything here is disabled"
 * read.
 */
const FEATURE_ICONS: Record<string, ComponentType<SvgIconProps>> = {
  source: LanguageOutlinedIcon,
  freshness: ScheduleOutlinedIcon,
  ai_labels: SellOutlinedIcon,
  curated: ApartmentOutlinedIcon,
  saved_filters: FilterListOutlinedIcon,
  free: LockOpenOutlinedIcon,
  mcp_access: SmartToyOutlinedIcon,
  ai_notifications: NotificationsNoneOutlinedIcon,
  track_any_company: TravelExploreOutlinedIcon,
};

/**
 * Zero-gap grid shared by both tiers: the per-cell top rules must meet to read
 * as a matrix, and the columns are separated by the cells' own right gutter
 * instead, so the rules stay continuous while the cells stop touching. Both
 * tiers use the identical template so the coming-soon group lands on the same
 * column edges as the live cells rather than beside a second, unrelated grid.
 */
const MATRIX_GRID_SX = {
  display: 'grid',
  gridTemplateColumns: {
    xs: 'repeat(2, minmax(0, 1fr))',
    sm: 'repeat(3, minmax(0, 1fr))',
  },
  gap: 0,
} as const;

interface MatrixCellProps {
  feature: LandingFeature;
  /**
   * Renders the cell in the disabled tier. Grayness is expressed ONE way —
   * `text.disabled` on the icon, name, and detail — rather than by a wrapper
   * `opacity`, so the cell's colours stay theme tokens (readable in either
   * palette) instead of a washed-out blend of text over background.
   */
  muted?: boolean;
  /**
   * Widens the cell to the full 2-column mobile row. Set only on a tier's
   * trailing cell when the tier has an odd count: alone in a 2-up row it would
   * otherwise draw a rule across half the matrix and stop, which reads as an
   * unfinished row rather than a closing one.
   */
  fillsMobileRow?: boolean;
}

function MatrixCell({ feature, muted = false, fillsMobileRow = false }: MatrixCellProps) {
  const Icon = FEATURE_ICONS[feature.id];
  return (
    <Box
      // `minWidth: 0` keeps a long detail line from widening its track past the
      // viewport at 390px.
      sx={{
        minWidth: 0,
        borderTop: '1px solid',
        borderColor: 'divider',
        py: RESPONSIVE.landingProto.matrixCellPaddingY,
        pr: RESPONSIVE.landingProto.matrixCellPaddingRight,
        ...(fillsMobileRow && { gridColumn: { xs: 'span 2', sm: 'span 1' } }),
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        {Icon && (
          <Icon
            aria-hidden
            sx={{ fontSize: 20, color: muted ? 'text.disabled' : 'text.primary', flexShrink: 0 }}
          />
        )}
        <Typography
          component="h3"
          sx={{
            fontSize: RESPONSIVE.landingProto.blockTitleFontSize,
            fontWeight: 600,
            ...(muted && { color: 'text.disabled' }),
          }}
        >
          {feature.name}
        </Typography>
      </Box>
      <Typography
        variant="body2"
        sx={{
          color: muted ? 'text.disabled' : 'text.secondary',
          fontSize: RESPONSIVE.landingProto.bodyFontSize,
          lineHeight: 1.65,
        }}
      >
        {feature.detail}
      </Typography>
    </Box>
  );
}

interface FeatureMatrixSectionProps {
  content: LandingContent;
}

/**
 * The feature matrix: every live capability, absorbable in about three seconds,
 * followed by a grayed-out coming-soon tier.
 *
 * Layout is a zero-gap CSS grid (2 columns on phones, 3 from `sm`) where each
 * cell draws its own top hairline, so adjacent cells fuse into continuous rules
 * and the block reads as a ruled matrix rather than floating cards. The live
 * tier's six-cell count is chosen to fill both grids exactly — no orphan cell.
 *
 * **Rules are load-bearing only where they separate rows.** The closing bottom
 * rule was dropped and the cells given deep vertical padding instead: Notion
 * separates with space, not lines, so each tier ends in air and the columns are
 * parted by each cell's own right gutter rather than by a vertical rule.
 *
 * **The coming-soon tier is a labeled exception, not a softening of the rule.**
 * `docs/marketing/business-context.md` still forbids anything unshipped from
 * reading as present-tense; the owner decision of 2026-08-20 recorded there
 * permits unshipped work on the page ONLY inside a tier that is visually
 * disabled AND named as such. Both halves are load-bearing, which is why the
 * tier carries an explicit "Coming soon" overline: gray alone is a hint, and a
 * hint is not a disclosure. Per-cell "SOON" chips were rejected for the
 * opposite reason — three shouting badges would cost the matrix the calm skim
 * it exists for, and one group label already says it once.
 *
 * The vote link still closes the section, now reading as the coda after the
 * roadmap instead of standing in for it.
 */
export function FeatureMatrixSection({ content }: FeatureMatrixSectionProps) {
  const { heading, features, comingSoonLabel, comingSoon, nextUp } = content.featureMatrix;

  return (
    <Box component="section" data-testid="feature-matrix">
      <Typography
        component="h2"
        sx={{
          fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
          fontWeight: 600,
          mb: RESPONSIVE.landingProto.sectionTitleMarginBottom,
        }}
      >
        {heading}
      </Typography>

      <Box data-testid="feature-matrix-live" sx={MATRIX_GRID_SX}>
        {features.map((feature) => (
          <MatrixCell key={feature.id} feature={feature} />
        ))}
      </Box>

      {/* The tier break is space, not a heavier rule: a small margin on top of
          the live cells' own deep bottom padding, then the overline sitting in
          that air above the group's first hairline. */}
      <Box data-testid="feature-matrix-coming-soon" sx={{ mt: { xs: 1, sm: 2 } }}>
        <Typography
          sx={{
            color: 'text.disabled',
            fontSize: RESPONSIVE.landingProto.matrixTierLabelFontSize,
            fontWeight: 600,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            mb: { xs: 1, sm: 1.5 },
          }}
        >
          {comingSoonLabel}
        </Typography>
        <Box sx={MATRIX_GRID_SX}>
          {comingSoon.map((feature, i) => (
            <MatrixCell
              key={feature.id}
              feature={feature}
              muted
              // Three cells fill the 3-up desktop row exactly but leave a lone
              // cell in the 2-up mobile grid; the trailing cell takes the whole
              // row there so the tier closes on a full-width rule.
              fillsMobileRow={comingSoon.length % 2 === 1 && i === comingSoon.length - 1}
            />
          ))}
        </Box>
      </Box>

      <Typography variant="body2" sx={{ mt: 3, fontSize: RESPONSIVE.landingProto.bodyFontSize }}>
        <Link component={RouterLink} to={nextUp.to} sx={{ color: 'text.secondary' }}>
          {nextUp.label}
        </Link>
      </Typography>
    </Box>
  );
}

export default FeatureMatrixSection;
