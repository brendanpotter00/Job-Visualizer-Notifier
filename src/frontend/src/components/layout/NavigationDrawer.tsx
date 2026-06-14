import { styled, useTheme, Theme, CSSObject } from '@mui/material/styles';
import MuiDrawer from '@mui/material/Drawer';
import Box from '@mui/material/Box';
import List from '@mui/material/List';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Tooltip from '@mui/material/Tooltip';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ScheduleIcon from '@mui/icons-material/Schedule';
import InfoIcon from '@mui/icons-material/Info';
import BugReportIcon from '@mui/icons-material/BugReport';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import ThumbUpIcon from '@mui/icons-material/ThumbUp';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import PeopleIcon from '@mui/icons-material/People';
import PlaceIcon from '@mui/icons-material/Place';
import { useNavigate, useLocation } from 'react-router-dom';
import { ADMIN_NAV_ITEMS, ROUTES, USER_NAV_ITEMS } from '../../config/routes.ts';
import { useAuth } from '../../features/auth/useAuth';
import { useCurrentUser } from '../../features/auth/useCurrentUser';

/**
 * Props for the NavigationDrawer component
 */
interface NavigationDrawerProps {
  /** Whether the drawer is currently open */
  open: boolean;
  /** Callback to close the drawer (for mobile) */
  onClose: () => void;
  /** Callback to toggle collapse state (for desktop) */
  onToggleCollapse: () => void;
  /** Drawer width in pixels */
  drawerWidth: number;
  /** Whether the current viewport is mobile */
  isMobile: boolean;
}

const openedMixin = (theme: Theme, drawerWidth: number): CSSObject => ({
  width: drawerWidth,
  transition: theme.transitions.create('width', {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.enteringScreen,
  }),
  overflowX: 'hidden',
});

const closedMixin = (theme: Theme): CSSObject => ({
  transition: theme.transitions.create('width', {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.leavingScreen,
  }),
  overflowX: 'hidden',
  width: `calc(${theme.spacing(7)} + 1px)`,
  [theme.breakpoints.up('sm')]: {
    width: `calc(${theme.spacing(8)} + 1px)`,
  },
});

const DrawerHeader = styled('div')(({ theme }) => ({
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'flex-end',
  padding: theme.spacing(0, 1),
  ...theme.mixins.toolbar,
}));

const PermanentDrawer = styled(MuiDrawer, {
  shouldForwardProp: (prop) => prop !== 'open' && prop !== 'drawerWidth',
})<{ open?: boolean; drawerWidth?: number }>(({ theme, open, drawerWidth = 240 }) => ({
  width: drawerWidth,
  flexShrink: 0,
  whiteSpace: 'nowrap',
  boxSizing: 'border-box',
  ...(open && {
    ...openedMixin(theme, drawerWidth),
    '& .MuiDrawer-paper': openedMixin(theme, drawerWidth),
  }),
  ...(!open && {
    ...closedMixin(theme),
    '& .MuiDrawer-paper': closedMixin(theme),
  }),
}));

type IconName =
  | 'Schedule'
  | 'Info'
  | 'BugReport'
  | 'AccountCircle'
  | 'ThumbUp'
  | 'TrendingUp'
  | 'People'
  | 'Place';
const iconMap: Record<IconName, React.ComponentType> = {
  Schedule: ScheduleIcon,
  Info: InfoIcon,
  BugReport: BugReportIcon,
  AccountCircle: AccountCircleIcon,
  ThumbUp: ThumbUpIcon,
  TrendingUp: TrendingUpIcon,
  People: PeopleIcon,
  Place: PlaceIcon,
};

export function NavigationDrawer({
  open,
  onClose,
  onToggleCollapse,
  drawerWidth,
  isMobile,
}: NavigationDrawerProps) {
  const theme = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated } = useAuth();
  const { user, error: userError, reload: reloadUser } = useCurrentUser();
  const isAdmin = !!user?.isAdmin;
  // Show the Admin status indicator only when the /api/users fetch
  // failed AND we have no cached user. If we have a cached user, the
  // existing isAdmin branch handles things. If the user just logged out
  // (isAuthenticated === false), there's no admin nav to surface.
  // ``userError && !user`` is the "auth backend outage" case where an
  // admin would otherwise silently lose admin nav.
  const adminStatusUnavailable = !!userError && !user && isAuthenticated;

  const handleNavigate = (path: string) => {
    navigate(path);
    if (isMobile) {
      onClose();
    }
  };

  function renderNavItem(path: string, label: string, icon: IconName) {
    const Icon = iconMap[icon];
    const isActive = location.pathname === path;

    return (
      <ListItem key={path} disablePadding sx={{ display: 'block' }}>
        <ListItemButton
          onClick={() => handleNavigate(path)}
          sx={[
            { minHeight: 48, px: 2.5 },
            open ? { justifyContent: 'initial' } : { justifyContent: 'center' },
            isActive && { bgcolor: 'action.selected' },
          ]}
        >
          <Tooltip title={label} placement="right" arrow disableHoverListener={open}>
            <ListItemIcon
              sx={[{ minWidth: 0, justifyContent: 'center' }, open ? { mr: 3 } : { mr: 'auto' }]}
            >
              <Icon />
            </ListItemIcon>
          </Tooltip>
          <ListItemText primary={label} sx={[open ? { opacity: 1 } : { opacity: 0 }]} />
        </ListItemButton>
      </ListItem>
    );
  }

  const renderAdminGroup = () => {
    if (!isAdmin) {
      if (adminStatusUnavailable) {
        // Auth backend outage: ``useCurrentUser`` returned ``error`` and
        // ``!user``. We don't know if the user is an admin. Hiding the
        // section entirely silently strips admin nav during an outage —
        // an admin who refreshes during a /api/users 500 sees their
        // surface disappear with no signal. Render a disabled,
        // inline-error affordance so they know to retry rather than
        // assuming their access was revoked.
        return (
          <>
            <Divider sx={{ my: 1 }} />
            <ListItem
              data-testid="admin-status-unavailable"
              disablePadding
              sx={{ display: 'block' }}
            >
              <Tooltip title="Admin status unavailable — retry" placement="right" arrow>
                <ListItemButton
                  onClick={() => reloadUser()}
                  sx={[
                    { minHeight: 48, px: 2.5 },
                    open ? { justifyContent: 'initial' } : { justifyContent: 'center' },
                  ]}
                  aria-label="Admin status unavailable — retry"
                >
                  <ListItemIcon
                    sx={[
                      { minWidth: 0, justifyContent: 'center' },
                      open ? { mr: 3 } : { mr: 'auto' },
                    ]}
                  >
                    <ErrorOutlineIcon color="warning" />
                  </ListItemIcon>
                  <ListItemText
                    primary="Admin status unavailable"
                    sx={[open ? { opacity: 1 } : { opacity: 0 }]}
                    slotProps={{
                      primary: {
                        sx: {
                          fontSize: 12,
                          color: 'text.secondary',
                        },
                      },
                    }}
                  />
                </ListItemButton>
              </Tooltip>
            </ListItem>
          </>
        );
      }
      return null;
    }

    // Collapsed drawer: render admin items flat (icons only). The "ADMIN"
    // caption would be invisible at 56px width since text labels are hidden,
    // and dropping the items entirely would be worse for the admin's daily use.
    if (!open) {
      return (
        <>
          <Divider sx={{ my: 1 }} />
          <List>
            {ADMIN_NAV_ITEMS.map((item) =>
              renderNavItem(item.path, item.label, item.icon as IconName)
            )}
          </List>
        </>
      );
    }

    return (
      <>
        <Divider sx={{ my: 1 }} />
        <Box sx={{ px: 2.5, pt: 1.25, pb: 0.5 }}>
          <Box
            sx={{
              fontSize: 11,
              letterSpacing: '0.18em',
              fontWeight: 700,
              color: 'text.secondary',
            }}
          >
            ADMIN
          </Box>
        </Box>
        <List component="div" disablePadding>
          {ADMIN_NAV_ITEMS.map((item) =>
            renderNavItem(item.path, item.label, item.icon as IconName)
          )}
        </List>
      </>
    );
  };

  const renderDrawerContent = () => (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <DrawerHeader>
        <IconButton onClick={isMobile ? onClose : onToggleCollapse}>
          {theme.direction === 'rtl' ? <ChevronRightIcon /> : <ChevronLeftIcon />}
        </IconButton>
      </DrawerHeader>
      <Divider />
      <List>
        {USER_NAV_ITEMS.map((item) => renderNavItem(item.path, item.label, item.icon as IconName))}
      </List>
      {renderAdminGroup()}
      {/* Spacer pushes the Account section to the bottom of the drawer.
          Without this, `mt: 'auto'` on the Account divider would push every
          sibling below the Admin group to the bottom — leaving the Admin
          group floating mid-drawer with a large gap. An explicit spacer
          makes the layout intent obvious and works regardless of whether
          the Admin section is rendered. */}
      <Box sx={{ flexGrow: 1 }} />
      {isAuthenticated && (
        <>
          <Divider />
          <List>{renderNavItem(ROUTES.ACCOUNT, 'Account', 'AccountCircle')}</List>
        </>
      )}
    </Box>
  );

  if (isMobile) {
    return (
      <MuiDrawer
        variant="temporary"
        open={open}
        onClose={onClose}
        ModalProps={{
          keepMounted: true,
        }}
        sx={{
          '& .MuiDrawer-paper': {
            width: drawerWidth,
          },
        }}
      >
        {renderDrawerContent()}
      </MuiDrawer>
    );
  }

  return (
    <PermanentDrawer variant="permanent" open={open} drawerWidth={drawerWidth}>
      {renderDrawerContent()}
    </PermanentDrawer>
  );
}
