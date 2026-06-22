import { Stack, Typography } from '@mui/material';
import { CompanySelector } from '../../components/companies-page/CompanySelector/CompanySelector';
import { useAppSelector } from '../../app/hooks';
import { getCompanyById } from '../../config/companies';
import { getCompanySourceLabel } from '../../config/atsSource';

/**
 * Companies page header component
 *
 * Displays the company name with job posting analytics title
 * and provides the company selector dropdown.
 *
 * @returns The companies page header with title and company selector
 */
export function CompaniesPageHeader() {
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const company = getCompanyById(selectedCompanyId);
  const companyNameHeaderTitle = company?.name || 'Job Posting Analytics';
  const companyATSSource = company ? getCompanySourceLabel(company) : 'Unknown Source';
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={2}
      alignItems={{ xs: 'flex-start', sm: 'center' }}
      justifyContent="space-between"
      sx={{ mb: 4 }}
    >
      <Stack>
        <Typography variant="h3" component="h1">
          {companyNameHeaderTitle}
        </Typography>
        <Typography variant="body1" color="text.disabled">
          Source: {companyATSSource}
        </Typography>
      </Stack>
      <CompanySelector />
    </Stack>
  );
}
