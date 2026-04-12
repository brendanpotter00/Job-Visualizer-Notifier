import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Typography from '@mui/material/Typography';
import CircularProgress from '@mui/material/CircularProgress';
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

  const loadUser = useCallback(async () => {
    setUserLoading(true);
    try {
      const token = await getToken();
      const fetchedUser = await fetchCurrentUser(token);
      setUser(fetchedUser);
    } catch (err) {
      console.error('[UserMenu] Failed to load user profile:', err);
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
      <Box sx={{ display: 'flex', alignItems: 'center', px: 1 }}>
        <CircularProgress size={24} color="inherit" />
      </Box>
    );
  }

  if (!isAuthenticated) {
    return (
      <Button variant="outlined" color="inherit" onClick={login} size="small">
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
