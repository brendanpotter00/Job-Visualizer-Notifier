import { capitalize, Stack, Typography } from '@mui/material';
import { CompanySelector } from '../../components/companies-page/CompanySelector/CompanySelector';
import { useAppSelector } from '../../app/hooks';
import { getCompanyById } from '../../config/companies';

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
  const companyNameHeaderTitle = getCompanyById(selectedCompanyId)?.name || 'Job Posting Analytics';
  const companyATSSource = capitalize(getCompanyById(selectedCompanyId)?.ats || 'Unknown Source');
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
          {companyNameHeaderTitle} - Job Posting Analytics
        </Typography>
        <Typography variant="body1" color="text.disabled">
          Source: {companyATSSource}
        </Typography>
      </Stack>
      <CompanySelector />
    </Stack>
  );
}
