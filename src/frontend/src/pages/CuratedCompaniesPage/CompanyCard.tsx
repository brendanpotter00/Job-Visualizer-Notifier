import { Box, Card, CardActionArea, CardContent, Typography } from '@mui/material';
import StarOutlineIcon from '@mui/icons-material/StarOutline';
import { Link as RouterLink } from 'react-router-dom';
import { CARD_HOVER_SX, CARD_VARIANT } from '../../components/shared/JobCard/jobCardStyles';
import { ROUTES } from '../../config/routes';
import { getCompanyById } from '../../config/companies';
import type { CuratedCompany } from '../../features/companies/companiesApi';

interface CompanyCardProps {
  company: CuratedCompany;
}

function CardBody({ company }: CompanyCardProps) {
  return (
    <CardContent
      sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 1 }}
    >
      <Typography variant="h6" component="h3">
        {company.displayName}
      </Typography>
      {company.blurb && (
        <Typography variant="body2" color="text.secondary">
          {company.blurb}
        </Typography>
      )}
      {company.accomplishment && (
        <Box
          sx={{ mt: 'auto', pt: 1, display: 'flex', gap: 0.75, alignItems: 'flex-start' }}
        >
          <StarOutlineIcon
            fontSize="small"
            aria-hidden
            sx={{ color: 'text.disabled', mt: '2px', flexShrink: 0 }}
          />
          <Typography variant="body2" color="text.secondary">
            {company.accomplishment}
          </Typography>
        </Box>
      )}
    </CardContent>
  );
}

/**
 * One company in the directory grid. The whole card deep-links to that
 * company's Company Hiring Trends view via `?company=<id>` — but only when the
 * id exists in the frontend config. `getInitialCompanyId()` validates the param
 * against `getCompanyById` and silently falls back to the default company
 * otherwise, so a DB-only id (e.g. `reducto`, present in the table but not the
 * config) renders as a non-interactive card rather than a misleading link.
 */
export function CompanyCard({ company }: CompanyCardProps) {
  const linkable = getCompanyById(company.id) !== undefined;

  if (!linkable) {
    return (
      <Card variant={CARD_VARIANT} sx={{ height: '100%' }}>
        <CardBody company={company} />
      </Card>
    );
  }

  return (
    <Card variant={CARD_VARIANT} sx={{ height: '100%', ...CARD_HOVER_SX }}>
      <CardActionArea
        component={RouterLink}
        to={`${ROUTES.COMPANIES}?company=${encodeURIComponent(company.id)}`}
        aria-label={`View hiring trends for ${company.displayName}`}
        sx={{ height: '100%', alignItems: 'stretch' }}
      >
        <CardBody company={company} />
      </CardActionArea>
    </Card>
  );
}
