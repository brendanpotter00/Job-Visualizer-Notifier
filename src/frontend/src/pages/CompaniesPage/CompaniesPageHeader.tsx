import { Stack, Typography } from '@mui/material';
import { RESPONSIVE } from '../../config/responsive';
import { CompanySelector } from '../../components/companies-page/CompanySelector/CompanySelector';
import { useAppSelector } from '../../app/hooks';
import { selectEffectiveCompanyById } from '../../features/userCompanies/effectiveCompanies';

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
  // Resolves curated companies AND the viewer's own boards. For a custom board
  // the name is `UserCompany.displayName` — already the effective name
  // server-side (`COALESCE(user_display_name, display_name)`), so a rename wins
  // here with nothing to merge — and the source line is the board's host rather
  // than the "Unknown Source" an unrecognized id used to get.
  const company = useAppSelector((state) => selectEffectiveCompanyById(state, selectedCompanyId));
  const companyNameHeaderTitle = company?.name || 'Job Posting Analytics';
  const companyATSSource = company?.sourceLabel ?? 'Unknown Source';
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={2}
      alignItems={{ xs: 'flex-start', sm: 'center' }}
      justifyContent="space-between"
      sx={{ mb: RESPONSIVE.spacing.pageMarginY }}
    >
      <Stack>
        <Typography variant="h3" component="h1" sx={{ fontSize: RESPONSIVE.fontSize.pageTitle }}>
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
