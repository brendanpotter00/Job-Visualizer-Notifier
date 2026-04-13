import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Typography from '@mui/material/Typography';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import { useAuth } from '../../features/auth/useAuth';
import { fetchCurrentUser, type User } from '../../features/auth/authService';
import { ROUTES } from '../../config/routes';

export function UserMenu() {
  const { isEnabled, isAuthenticated, isLoading, login, logout, getToken } = useAuth();
  const navigate = useNavigate();

  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [user, setUser] = useState<User | null>(null);
  const [userLoading, setUserLoading] = useState(false);
  const [userError, setUserError] = useState(false);

  const loadUser = useCallback(async () => {
    setUserLoading(true);
    setUserError(false);
    try {
      const token = await getToken();
      const fetchedUser = await fetchCurrentUser(token);
      setUser(fetchedUser);
    } catch (err) {
      console.error('[UserMenu] Failed to load user profile:', err);
      setUserError(true);
    } finally {
      setUserLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    if (isAuthenticated) {
      loadUser();
    } else {
      setUser(null);
    }
  }, [isAuthenticated, loadUser]);

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
      <Button
        variant="outlined"
        color="inherit"
        onClick={login}
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
        {userLoading ? (
          <MenuItem disabled>
            <CircularProgress size={16} sx={{ mr: 1 }} />
            Loading...
          </MenuItem>
        ) : userError && !user ? (
          <MenuItem disabled>
            <Typography variant="caption" color="error">
              Failed to load profile
            </Typography>
          </MenuItem>
        ) : (
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
        )}
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
