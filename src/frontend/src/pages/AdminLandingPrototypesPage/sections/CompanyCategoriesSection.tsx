import { Box, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { CompanyLogo } from '../../../components/shared/CompanyLogo/CompanyLogo';
import { getCompanyById } from '../../../config/companies';
import { RESPONSIVE } from '../../../config/responsive';
import { ROUTES } from '../../../config/routes';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { COMPANY_CATEGORIES } from '../companyCategories';

/**
 * Logos rendered on each card before the rest collapse into "+N". The category
 * roster is ordered most-recognizable-first (see `companyCategories.ts`), so
 * this is a plain head slice — no sorting, no randomness.
 */
const VISIBLE_LOGOS = 6;

/**
 * "Browse curated companies" — the curated entry points into the board.
 *
 * Every card links to the jobs board as-is. Real preset filters (a category
 * slug becoming `?category=ai_labs` or an expanded company multi-select) arrive
 * when this section is promoted out of the prototypes page; wiring query params
 * now would ship dead params against an endpoint that ignores them, so the
 * mock target is deliberate and OUT OF SCOPE here.
 */
export function CompanyCategoriesSection() {
  const isMobile = useIsMobile();
  const logoSize = isMobile
    ? RESPONSIVE.landingProto.tickerLogoSize.compact
    : RESPONSIVE.landingProto.tickerLogoSize.default;

  return (
    <Box component="section">
      <Typography
        component="h2"
        sx={{
          fontSize: RESPONSIVE.landingProto.sectionTitleFontSize,
          fontWeight: 600,
          mb: 1,
        }}
      >
        Browse curated companies
      </Typography>
      {/* Heading + subtitle stay a tight pair; the air goes BELOW them, so the
          heading block floats above the grid instead of leaning on it. */}
      <Typography
        variant="body2"
        sx={{
          color: 'text.secondary',
          fontSize: RESPONSIVE.landingProto.bodyFontSize,
          lineHeight: 1.7,
          mb: RESPONSIVE.landingProto.sectionTitleMarginBottom,
        }}
      >
        Hand-picked companies, grouped the way people actually search.
      </Typography>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            sm: 'repeat(2, minmax(0, 1fr))',
            md: 'repeat(3, minmax(0, 1fr))',
          },
          gap: RESPONSIVE.landingProto.categoryGridGap,
        }}
      >
        {COMPANY_CATEGORIES.map((category) => {
          const visible = category.companyIds.slice(0, VISIBLE_LOGOS);
          const overflow = category.companyIds.length - visible.length;
          const count = `${category.companyIds.length} companies`;

          return (
            <Box
              key={category.id}
              component={RouterLink}
              to={ROUTES.RECENT_JOBS}
              aria-label={`${category.label}, ${count}`}
              sx={{
                display: 'flex',
                flexDirection: 'column',
                gap: 1.25,
                // `minWidth: 0` keeps a long blurb from forcing the grid track
                // wider than the viewport on a narrow phone.
                minWidth: 0,
                p: RESPONSIVE.landingProto.categoryCardPadding,
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 1,
                bgcolor: 'background.paper',
                color: 'inherit',
                textDecoration: 'none',
                transition: 'border-color 120ms ease, background-color 120ms ease',
                '&:hover': {
                  borderColor: 'text.primary',
                  bgcolor: 'action.hover',
                },
              }}
            >
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  gap: 1,
                }}
              >
                <Typography
                  component="h3"
                  sx={{ fontWeight: 600, fontSize: RESPONSIVE.landingProto.blockTitleFontSize }}
                >
                  {category.label}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ color: 'text.secondary', flexShrink: 0, whiteSpace: 'nowrap' }}
                >
                  {count}
                </Typography>
              </Box>

              <Typography
                variant="body2"
                sx={{
                  color: 'text.secondary',
                  fontSize: RESPONSIVE.landingProto.bodyFontSize,
                  lineHeight: 1.6,
                }}
              >
                {category.blurb}
              </Typography>

              <Box
                sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mt: 1.5, flexWrap: 'wrap' }}
              >
                {visible.map((companyId) => (
                  <CompanyLogo
                    key={companyId}
                    companyId={companyId}
                    displayName={getCompanyById(companyId)?.name ?? companyId}
                    size={logoSize}
                  />
                ))}
                {overflow > 0 && (
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    +{overflow}
                  </Typography>
                )}
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}

export default CompanyCategoriesSection;
