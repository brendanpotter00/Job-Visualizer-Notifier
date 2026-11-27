import type { MouseEvent } from 'react';
import { Box, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { useAppDispatch } from '../../../app/hooks';
import { CompanyLogo } from '../../../components/shared/CompanyLogo/CompanyLogo';
import { getCompanyById } from '../../../config/companies';
import { COMPANY_CATEGORIES } from '../../../config/companyCategories';
import { RESPONSIVE } from '../../../config/responsive';
import {
  resetRecentJobsFilters,
  setRecentJobsCompanyCategory,
} from '../../../features/filters/slices/recentJobsFiltersSlice';
import { recentJobsHrefForCompanyType } from '../../../features/filters/urlFilters';
import { useIsMobile } from '../../../hooks/useIsMobile';
import type { LandingContent } from '../content';
import { SectionIntro } from './SectionIntro';

const HEADING_ID = 'landing-companies-heading';

/**
 * Logos rendered on each card before the rest collapse into "+N". Each
 * category's `companyIds` is ordered most-recognizable-first (see
 * `config/companyCategories.ts`), so this is a plain head slice: no sorting,
 * no randomness.
 */
const VISIBLE_LOGOS = 6;

/** A click the browser handles itself (new tab, new window, download). */
function isModifiedClick(event: MouseEvent): boolean {
  return event.button !== 0 || event.metaKey || event.altKey || event.ctrlKey || event.shiftKey;
}

interface CompanyCategoriesSectionProps {
  content: LandingContent;
}

/**
 * "Curated Companies": one card per company type, each opening Recent Job
 * Postings already filtered to it (`/jobs?company_type=<slug>`).
 *
 * The click resets the Recent filters, sets the type, then lets the router
 * navigate (an SPA move, never a full page load, which would fire
 * `signup_funnel_landing` again). Setting the slice here is not redundant with
 * the link: `useRecentJobsUrlSync` reads the URL once per app mount, so a
 * visitor who went to `/jobs`, came Back and picked another card would
 * otherwise keep the first card's filter. The link still carries the type, so
 * copying it or opening it in a new tab works on its own.
 *
 * 10 cards, laid out with no card left alone on a row: 1 column on a phone,
 * 2 up to `lg`, then 5.
 */
export function CompanyCategoriesSection({ content }: CompanyCategoriesSectionProps) {
  const { heading } = content.companies;
  const dispatch = useAppDispatch();
  const isMobile = useIsMobile();
  const logoSize = isMobile
    ? RESPONSIVE.landingProto.tickerLogoSize.compact
    : RESPONSIVE.landingProto.tickerLogoSize.default;

  const selectCompanyType = (slug: string) => (event: MouseEvent) => {
    if (event.defaultPrevented || isModifiedClick(event)) return;
    dispatch(resetRecentJobsFilters());
    dispatch(setRecentJobsCompanyCategory([slug]));
  };

  return (
    <Box component="section" aria-labelledby={HEADING_ID}>
      <SectionIntro heading={heading} headingId={HEADING_ID} />

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            sm: 'repeat(2, minmax(0, 1fr))',
            lg: 'repeat(5, minmax(0, 1fr))',
          },
          gap: RESPONSIVE.landingProto.categoryGridGap,
        }}
      >
        {COMPANY_CATEGORIES.map((category) => {
          const visible = category.companyIds.slice(0, VISIBLE_LOGOS);
          const overflow = category.companyIds.length - visible.length;

          return (
            <Box
              key={category.slug}
              component={RouterLink}
              to={recentJobsHrefForCompanyType(category.slug)}
              onClick={selectCompanyType(category.slug)}
              aria-label={category.label}
              sx={{
                display: 'flex',
                flexDirection: 'column',
                gap: 1.25,
                // `minWidth: 0` keeps a long label from forcing the grid track
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
              <Typography
                component="h3"
                sx={{ fontWeight: 500, fontSize: RESPONSIVE.landingProto.blockTitleFontSize }}
              >
                {category.label}
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
