import { Stack, Typography } from '@mui/material';
import { CompanySelector } from '../CompanySelector/CompanySelector';

/**
 * Props for the AppHeader component
 */
interface AppHeaderProps {
  /** Display name of the currently selected company */
  companyName: string;
}

/**
 * Application header component
 *
 * Displays the application title with the selected company name
 * and provides the company selector dropdown.
 *
 * @param props - Component props
 * @returns The application header with title and company selector
 */
export function AppHeader({ companyName }: AppHeaderProps) {
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={2}
      alignItems={{ xs: 'flex-start', sm: 'center' }}
      justifyContent="space-between"
      sx={{ mb: 4 }}
    >
      <Typography variant="h3" component="h1">
        {companyName} - Job Posting Analytics
      </Typography>
      <CompanySelector />
    </Stack>
  );
}
