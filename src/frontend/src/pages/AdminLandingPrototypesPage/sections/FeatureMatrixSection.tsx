import type { ComponentType } from 'react';
import { Box, Link, Typography } from '@mui/material';
import type { SvgIconProps } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import ApartmentOutlinedIcon from '@mui/icons-material/ApartmentOutlined';
import FilterListOutlinedIcon from '@mui/icons-material/FilterListOutlined';
import LanguageOutlinedIcon from '@mui/icons-material/LanguageOutlined';
import LockOpenOutlinedIcon from '@mui/icons-material/LockOpenOutlined';
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined';
import SellOutlinedIcon from '@mui/icons-material/SellOutlined';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingContent } from '../content';

/**
 * Icon per feature id. Icons are presentation, not copy, so the mapping lives
 * here rather than in `content.ts`. Outlined variants only, inheriting the text
 * colour — a coloured icon set would fight the monochrome page harder than the
 * physics hero does.
 */
const FEATURE_ICONS: Record<string, ComponentType<SvgIconProps>> = {
  source: LanguageOutlinedIcon,
  freshness: ScheduleOutlinedIcon,
  ai_labels: SellOutlinedIcon,
  curated: ApartmentOutlinedIcon,
  saved_filters: FilterListOutlinedIcon,
  free: LockOpenOutlinedIcon,
};

interface FeatureMatrixSectionProps {
  content: LandingContent;
}

/**
 * The feature matrix: every live capability, absorbable in about three seconds.
 *
 * Layout is a zero-gap CSS grid (2 columns on phones, 3 from `sm`) where each
 * cell draws its own top hairline, so adjacent cells fuse into continuous rules
 * and the block reads as a ruled matrix rather than six floating cards. The
 * six-cell count is chosen to fill both grids exactly — no orphan cell.
 *
 * **Rules are load-bearing only where they separate rows.** The closing bottom
 * rule was dropped and the cells given deep vertical padding instead: Notion
 * separates with space, not lines, so the matrix now ends in air (2 hairlines
 * on desktop instead of 3) and the columns are parted by each cell's own right
 * gutter rather than by a vertical rule.
 *
 * **Live features only, deliberately.** A "Soon" tier (watch any company,
 * alerts, saved jobs) was considered and dropped: `docs/marketing/business-
 * context.md` is explicit that nothing unshipped may read as present-tense on
 * the landing page, and a second visual tier would have cost the matrix the
 * three-second read it exists for. The honest answer to "what's next" is the
 * community vote page, which is the section's single closing link.
 */
export function FeatureMatrixSection({ content }: FeatureMatrixSectionProps) {
  const { heading, features, nextUp } = content.featureMatrix;

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

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: 'repeat(2, minmax(0, 1fr))',
            sm: 'repeat(3, minmax(0, 1fr))',
          },
          // Zero gap: the per-cell top rules must meet to read as a matrix. The
          // columns are separated by the cells' own right gutter instead, so the
          // rules stay continuous while the cells stop touching.
          gap: 0,
        }}
      >
        {features.map((feature) => {
          const Icon = FEATURE_ICONS[feature.id];
          return (
            <Box
              key={feature.id}
              // `minWidth: 0` keeps a long detail line from widening its track
              // past the viewport at 390px.
              sx={{
                minWidth: 0,
                borderTop: '1px solid',
                borderColor: 'divider',
                py: RESPONSIVE.landingProto.matrixCellPaddingY,
                pr: RESPONSIVE.landingProto.matrixCellPaddingRight,
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                {Icon && (
                  <Icon aria-hidden sx={{ fontSize: 20, color: 'text.primary', flexShrink: 0 }} />
                )}
                <Typography
                  component="h3"
                  sx={{ fontSize: RESPONSIVE.landingProto.blockTitleFontSize, fontWeight: 600 }}
                >
                  {feature.name}
                </Typography>
              </Box>
              <Typography
                variant="body2"
                sx={{
                  color: 'text.secondary',
                  fontSize: RESPONSIVE.landingProto.bodyFontSize,
                  lineHeight: 1.65,
                }}
              >
                {feature.detail}
              </Typography>
            </Box>
          );
        })}
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
