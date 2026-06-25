import { Card, CardActions, CardContent, Link, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { CARD_VARIANT } from '../../components/shared/JobCard/jobCardStyles';
import { CompanyWordmark } from '../../components/shared/CompanyLogo/CompanyWordmark';
import { ROUTES } from '../../config/routes';
import { getCompanyById } from '../../config/companies';
import { RESPONSIVE } from '../../config/responsive';
import { useIsMobile } from '../../hooks/useIsMobile';
import type { CuratedCompany } from '../../features/companies/companiesApi';

interface CompanyCardProps {
  company: CuratedCompany;
}

/**
 * One company in the directory grid: name, a single cohesive description
 * (blurb + accomplishment), and an explicit "See company hiring trends" link.
 *
 * The link only renders when the company exists in the frontend config —
 * `getInitialCompanyId()` validates `?company=<id>` against `getCompanyById`
 * and silently falls back to the default company otherwise, so a DB-only id
 * (present in the table but not the config) shows no link rather than a
 * misleading one.
 */
export function CompanyCard({ company }: CompanyCardProps) {
  const isMobile = useIsMobile();
  const linkable = getCompanyById(company.id) !== undefined;

  // Blurb + accomplishment read as one cohesive paragraph (omit whichever is null).
  const description = [company.blurb, company.accomplishment].filter(Boolean).join(' ');

  return (
    <Card variant={CARD_VARIANT} sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent
        sx={{
          flexGrow: 1,
          p: RESPONSIVE.curatedCard.contentPadding,
          '&:last-child': { pb: RESPONSIVE.curatedCard.contentPadding },
        }}
      >
        <CompanyWordmark
          companyId={company.id}
          displayName={company.displayName}
          height={
            isMobile
              ? RESPONSIVE.curatedCard.wordmarkHeight.compact
              : RESPONSIVE.curatedCard.wordmarkHeight.default
          }
        />
        {/* Keep the full blurb on every viewport — on mobile it just renders in
            a smaller font (no clamp/truncation), so the company explanation is
            always fully readable while the card stays more compact than before. */}
        {description && (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ fontSize: RESPONSIVE.curatedCard.descriptionFontSize }}
          >
            {description}
          </Typography>
        )}
      </CardContent>
      {linkable && (
        <CardActions sx={{ px: RESPONSIVE.curatedCard.contentPadding, pb: RESPONSIVE.curatedCard.contentPadding, pt: 0 }}>
          <Link
            component={RouterLink}
            to={`${ROUTES.COMPANIES}?company=${encodeURIComponent(company.id)}`}
            variant="body2"
          >
            See company hiring trends →
          </Link>
        </CardActions>
      )}
    </Card>
  );
}
