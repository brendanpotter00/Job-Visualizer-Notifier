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

export function UserMenu() {
  const { isEnabled, isAuthenticated, isLoading, login, logout } = useAuth();
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
      setLoginError(err instanceof Error ? err.message : 'Sign-in failed');
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

  const displayName =
    user?.displayName || [user?.givenName, user?.familyName].filter(Boolean).join(' ') || '';
  const initials = [user?.givenName?.[0], user?.familyName?.[0]].filter(Boolean).join('');

  const avatarSize = { width: 32, height: 32 };

  function renderAvatar() {
    if (user?.pictureUrl) {
      return <Avatar src={user.pictureUrl} sx={avatarSize} alt={displayName} />;
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
          {user?.email && (
            <Typography variant="caption" color="text.secondary">
              {user.email}
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
