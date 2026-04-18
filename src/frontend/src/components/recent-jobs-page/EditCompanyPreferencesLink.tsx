import { Box, Link, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useAppSelector } from '../../app/hooks';
import { useAuth } from '../../features/auth/useAuth';
import { selectEnabledCompanyIds } from '../../features/preferences/enabledCompaniesSlice';
import { ROUTES } from '../../config/routes';

export function EditCompanyPreferencesLink() {
  const { isAuthenticated, isLoading, login } = useAuth();
  const enabledIds = useAppSelector(selectEnabledCompanyIds);
  const navigate = useNavigate();

  // Reserve caption height while auth or signed-in preferences resolve to
  // avoid a layout shift when the text appears.
  if (isLoading || (isAuthenticated && enabledIds === null)) {
    return <Box sx={{ height: 20, mb: 2 }} aria-hidden />;
  }

  if (!isAuthenticated) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        <Link
          component="button"
          type="button"
          onClick={() => {
            void login();
          }}
          underline="hover"
          data-testid="sign-in-to-edit-preferences-link"
          sx={{ verticalAlign: 'baseline' }}
        >
          Sign in
        </Link>{' '}
        to customize this feed to the companies you care about
      </Typography>
    );
  }

  const count = enabledIds?.length ?? 0;
  const descriptor =
    count === 0
      ? 'all companies'
      : `your ${count} enabled ${count === 1 ? 'company' : 'companies'}`;
  const linkLabel = count === 0 ? 'Choose your companies' : 'Customize';

  return (
    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
      Showing jobs from {descriptor}
      {' · '}
      <Link
        component="button"
        type="button"
        onClick={() => navigate(ROUTES.ACCOUNT)}
        underline="hover"
        data-testid="edit-company-preferences-link"
        sx={{ verticalAlign: 'baseline' }}
      >
        {linkLabel}
      </Link>
    </Typography>
  );
}
