import { Box } from '@mui/material';
import { EditCompanyPreferencesLink } from './EditCompanyPreferencesLink';
import { NewFeatureCallout } from '../shared/NewFeatureCallout';

export function EditCompanyPreferencesRow() {
  return (
    <Box
      data-testid="edit-company-preferences-row"
      sx={{
        display: 'flex',
        flexDirection: { xs: 'column', md: 'row' },
        alignItems: { xs: 'flex-start', md: 'center' },
        gap: 1,
        mb: 2,
      }}
    >
      <EditCompanyPreferencesLink />
      {/* onClick omitted intentionally: the existing "Customize"/"Sign in"
          link sits right next to the pill, so the callout stays purely
          informational for v1. */}
      <NewFeatureCallout
        storageKey="companyPreferences-2026-04"
        expiresAt="2026-05-02T00:00:00Z"
        label="New! Pick your companies"
      />
    </Box>
  );
}
