import { Card, CardActions, CardContent, Link, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { CARD_VARIANT } from '../../components/shared/JobCard/jobCardStyles';
import { ROUTES } from '../../config/routes';
import { getCompanyById } from '../../config/companies';
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
 * (e.g. `reducto`, present in the table but not the config) shows no link
 * rather than a misleading one.
 */
export function CompanyCard({ company }: CompanyCardProps) {
  const linkable = getCompanyById(company.id) !== undefined;

  // Blurb + accomplishment read as one cohesive paragraph (omit whichever is null).
  const description = [company.blurb, company.accomplishment].filter(Boolean).join(' ');

  return (
    <Card variant={CARD_VARIANT} sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flexGrow: 1 }}>
        <Typography variant="h6" component="h3" gutterBottom>
          {company.displayName}
        </Typography>
        {description && (
          <Typography variant="body2" color="text.secondary">
            {description}
          </Typography>
        )}
      </CardContent>
      {linkable && (
        <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
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
