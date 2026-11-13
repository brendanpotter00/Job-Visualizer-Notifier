import { Button, type ButtonProps } from '@mui/material';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { ROUTES } from '../../../config/routes';
import { useAuth } from '../../../features/auth/useAuth';
import { trackSignInClick, type SignInLocation } from '../../../features/analytics/events';
import type { LandingCta } from '../content';

interface AuthEntryButtonProps extends Omit<ButtonProps, 'onClick' | 'href'> {
  cta: LandingCta;
  mode: 'login' | 'signup';
  location: SignInLocation;
}

export function AuthEntryButton({ cta, mode, location, ...buttonProps }: AuthEntryButtonProps) {
  const { isEnabled, isAuthenticated, login, signup } = useAuth();
  const navigate = useNavigate();

  if (!isEnabled) {
    return (
      <Button component={RouterLink} to={cta.to} {...buttonProps}>
        {cta.label}
      </Button>
    );
  }

  const handleClick = async () => {
    if (isAuthenticated) {
      navigate(ROUTES.RECENT_JOBS);
      return;
    }
    trackSignInClick(location);
    try {
      await (mode === 'signup' ? signup() : login());
    } catch {
      navigate(cta.to);
    }
  };

  return (
    <Button onClick={handleClick} {...buttonProps}>
      {cta.label}
    </Button>
  );
}
