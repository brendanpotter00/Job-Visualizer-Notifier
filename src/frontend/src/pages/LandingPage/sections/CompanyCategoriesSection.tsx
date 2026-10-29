import { Box, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { CompanyLogo } from '../../../components/shared/CompanyLogo/CompanyLogo';
import { getCompanyById } from '../../../config/companies';
import { RESPONSIVE } from '../../../config/responsive';
import { ROUTES } from '../../../config/routes';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { COMPANY_CATEGORIES } from '../companyCategories';
import type { LandingContent } from '../content';
import { SectionIntro } from './SectionIntro';

const HEADING_ID = 'landing-companies-heading';

/**
 * Logos rendered on each card before the rest collapse into "+N". The category
 * roster is ordered most-recognizable-first (see `companyCategories.ts`), so
 * this is a plain head slice — no sorting, no randomness.
 */
const VISIBLE_LOGOS = 6;

interface CompanyCategoriesSectionProps {
  content: LandingContent;
}

/**
 * "Browse curated companies" — the curated entry points into the board.
 *
 * Every card links to the jobs board as-is. Real preset filters (a category
 * slug becoming `?category=ai_labs` or an expanded company multi-select) arrive
 * when this section is promoted off the mock-backed landing page; wiring query params
 * now would ship dead params against an endpoint that ignores them, so the
 * mock target is deliberate and OUT OF SCOPE here.
 */
export function CompanyCategoriesSection({ content }: CompanyCategoriesSectionProps) {
  const { eyebrow, heading } = content.companies;
  const isMobile = useIsMobile();
  const logoSize = isMobile
    ? RESPONSIVE.landingProto.tickerLogoSize.compact
    : RESPONSIVE.landingProto.tickerLogoSize.default;

  return (
    <Box component="section" aria-labelledby={HEADING_ID}>
      <SectionIntro eyebrow={eyebrow} heading={heading} headingId={HEADING_ID} />

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
                borderRadius: 2,
                bgcolor: 'background.default',
                color: 'inherit',
                textDecoration: 'none',
                transition: 'border-color 120ms ease',
                '&:hover': { borderColor: 'text.primary' },
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
                  sx={{ fontWeight: 500, fontSize: RESPONSIVE.landingProto.blockTitleFontSize }}
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
