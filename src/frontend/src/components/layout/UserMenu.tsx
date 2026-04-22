import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Snackbar from '@mui/material/Snackbar';
import Typography from '@mui/material/Typography';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import { useAuth } from '../../features/auth/useAuth';
import { useCurrentUser } from '../../features/auth/useCurrentUser';
import { ROUTES } from '../../config/routes';
import { extractErrorMessage } from '../../lib/errors';

export function UserMenu() {
  const { isEnabled, isAuthenticated, isLoading, login, logout, user: auth0User } = useAuth();
  const { user, loading: userLoading, error: userError } = useCurrentUser();
  const navigate = useNavigate();

  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  // `login()` now rethrows Auth0 redirect failures (pop-up blocker, CSP,
  // misconfigured redirect URI). Surface those to the user instead of
  // letting them become unhandled promise rejections.
  const [loginError, setLoginError] = useState<string | null>(null);

  async function handleLogin() {
    try {
      setLoginError(null);
      await login();
    } catch (err) {
      setLoginError(extractErrorMessage(err, 'Sign-in failed'));
    }
  }

  if (!isEnabled) return null;

  if (isLoading) {
    return (
      <Button variant="outlined" color="inherit" size="small" disabled>
        Sign In
      </Button>
    );
  }

  if (!isAuthenticated) {
    return (
      <>
        <Button
          variant="outlined"
          color="inherit"
          onClick={handleLogin}
          size="small"
          sx={{
            transition: 'background-color 0.2s, border-color 0.2s',
            '&:hover': {
              backgroundColor: 'rgba(255, 255, 255, 0.25)',
              borderColor: '#fff',
            },
          }}
        >
          Sign In
        </Button>
        <Snackbar
          open={!!loginError}
          autoHideDuration={6000}
          onClose={() => setLoginError(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert onClose={() => setLoginError(null)} severity="error" sx={{ width: '100%' }}>
            {loginError}
          </Alert>
        </Snackbar>
      </>
    );
  }

  // Prefer backend profile; fall back to Auth0 ID-token claims so the avatar
  // still renders if the Post Login Action hasn't enriched the access token.
  const pictureUrl = user?.pictureUrl || auth0User?.picture || null;
  const givenName = user?.givenName || auth0User?.given_name || null;
  const familyName = user?.familyName || auth0User?.family_name || null;
  const email = user?.email || auth0User?.email || '';

  const displayName =
    user?.displayName || [givenName, familyName].filter(Boolean).join(' ') || '';
  const initials = [givenName?.[0], familyName?.[0]].filter(Boolean).join('');

  const avatarSize = { width: 32, height: 32 };

  function renderAvatar() {
    if (pictureUrl) {
      return <Avatar src={pictureUrl} sx={avatarSize} alt={displayName} />;
    }
    if (initials) {
      return <Avatar sx={{ ...avatarSize, fontSize: '0.875rem' }}>{initials}</Avatar>;
    }
    return <AccountCircleIcon sx={{ ...avatarSize, color: 'inherit' }} />;
  }

  function renderMenuContent() {
    if (userLoading) {
      return (
        <MenuItem disabled>
          <CircularProgress size={16} sx={{ mr: 1 }} />
          Loading...
        </MenuItem>
      );
    }
    if (userError && !user) {
      return (
        <MenuItem disabled>
          <Typography variant="caption" color="error">
            {userError}
          </Typography>
        </MenuItem>
      );
    }
    return (
      <MenuItem disabled>
        <Box>
          {displayName && (
            <Typography variant="body2" fontWeight={600}>
              {displayName}
            </Typography>
          )}
          {email && (
            <Typography variant="caption" color="text.secondary">
              {email}
            </Typography>
          )}
        </Box>
      </MenuItem>
    );
  }

  return (
    <>
      <IconButton
        onClick={(e) => setAnchorEl(e.currentTarget)}
        size="small"
        aria-label="user menu"
        aria-controls={anchorEl ? 'user-menu' : undefined}
        aria-haspopup="true"
        aria-expanded={anchorEl ? 'true' : undefined}
      >
        {renderAvatar()}
      </IconButton>
      <Menu
        id="user-menu"
        anchorEl={anchorEl}
        open={!!anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        {renderMenuContent()}
        <Divider />
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            navigate(ROUTES.ACCOUNT);
          }}
        >
          Account
        </MenuItem>
        <MenuItem
          onClick={() => {
            setAnchorEl(null);
            logout();
          }}
        >
          Sign Out
        </MenuItem>
      </Menu>
    </>
  );
}
