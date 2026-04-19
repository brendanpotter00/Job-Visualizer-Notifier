import { Box, Link, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useAppSelector } from '../../app/hooks';
import { useAuth } from '../../features/auth/useAuth';
import { selectEnabledCompanyIds } from '../../features/preferences/enabledCompaniesSlice';
import { ROUTES } from '../../config/routes';

export function EditCompanyPreferencesLink() {
  const { isAuthenticated, login } = useAuth();
  const enabledIds = useAppSelector(selectEnabledCompanyIds);
  const navigate = useNavigate();

  // Placeholder only when the signed-in branch is mid-fetch (enabledIds is null).
  // During auth loading we fall through by design: unauthenticated visitors see
  // the sign-in caption immediately; authenticated users (including a returning
  // Google user whose credential rehydrates synchronously) still hit this
  // placeholder because enabledIds stays null until the preferences query
  // resolves. If auth later resolves from unauthenticated to signed-in, the
  // component re-renders into the "Showing jobs from…" caption — a one-time
  // caption swap, strictly better than the sibling NewFeatureCallout pill
  // rendering with no adjacent caption.
  if (isAuthenticated && enabledIds === null) {
    return <Box sx={{ height: 20 }} aria-hidden />;
  }

  if (!isAuthenticated) {
    return (
      <Typography variant="body2" color="text.secondary">
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
    <Typography variant="body2" color="text.secondary">
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
