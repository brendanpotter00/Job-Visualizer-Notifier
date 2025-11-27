import { capitalize, Stack, Typography } from '@mui/material';
import { CompanySelector } from '../CompanySelector/CompanySelector';
import { useAppSelector } from '../../app/hooks.ts';
import { getCompanyById } from '../../config/companies.ts';

/**
 * Application header component
 *
 * Displays the application title with the selected company name
 * and provides the company selector dropdown.
 *
 * @returns The application header with title and company selector
 */
export function AppHeader() {
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
