import { useEffect, useState } from 'react';
import { styled, useTheme, Theme, CSSObject } from '@mui/material/styles';
import MuiDrawer from '@mui/material/Drawer';
import List from '@mui/material/List';
import Collapse from '@mui/material/Collapse';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Tooltip from '@mui/material/Tooltip';
import ScheduleIcon from '@mui/icons-material/Schedule';
import InfoIcon from '@mui/icons-material/Info';
import BugReportIcon from '@mui/icons-material/BugReport';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import ThumbUpIcon from '@mui/icons-material/ThumbUp';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import PeopleIcon from '@mui/icons-material/People';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
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
  | 'AdminPanelSettings';
const iconMap: Record<IconName, React.ComponentType> = {
  Schedule: ScheduleIcon,
  Info: InfoIcon,
  BugReport: BugReportIcon,
  AccountCircle: AccountCircleIcon,
  ThumbUp: ThumbUpIcon,
  TrendingUp: TrendingUpIcon,
  People: PeopleIcon,
  AdminPanelSettings: AdminPanelSettingsIcon,
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
  const { user } = useCurrentUser();
  const isAdmin = !!user?.isAdmin;

  // Default the Admin section to expanded for admins so the items are
  // immediately visible after login. `isAdmin` flips from false → true
  // asynchronously once `/api/users` resolves, so a `useState(isAdmin)`
  // initial value alone would lock the section closed for the rest of the
  // session. The effect mirrors the latest known admin status into local UI
  // state, but only on the *true* edge — once the admin manually toggles it
  // shut, later renders leave their choice alone.
  const [adminOpen, setAdminOpen] = useState(false);
  useEffect(() => {
    if (isAdmin) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional external-sync pattern; mirrors useCurrentUser's async admin flag into local UI state on the true edge only, so admins land on an expanded section after the /api/users fetch resolves without trapping a manual collapse
      setAdminOpen(true);
    }
  }, [isAdmin]);

  const handleNavigate = (path: string) => {
    navigate(path);
    if (isMobile) {
      onClose();
    }
  };

  function renderNavItem(
    path: string,
    label: string,
    icon: IconName,
    options: { indent?: boolean } = {}
  ) {
    const Icon = iconMap[icon];
    const isActive = location.pathname === path;
    const { indent } = options;

    return (
      <ListItem key={path} disablePadding sx={{ display: 'block' }}>
        <ListItemButton
          onClick={() => handleNavigate(path)}
          sx={[
            { minHeight: 48, px: 2.5 },
            open ? { justifyContent: 'initial' } : { justifyContent: 'center' },
            open && indent ? { pl: 4 } : null,
            isActive && { bgcolor: 'action.selected' },
          ]}
        >
          <Tooltip title={label} placement="right" arrow disableHoverListener={open}>
            <ListItemIcon
              sx={[
                { minWidth: 0, justifyContent: 'center' },
                open ? { mr: 3 } : { mr: 'auto' },
              ]}
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
    if (!isAdmin) return null;

    // Collapsed drawer: render admin items flat (icons only) — the accordion
    // chevron and "ADMIN" caption would be invisible at 56px width, and
    // hiding the items entirely would be worse for the admin's daily use.
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
        <ListItemButton
          onClick={() => setAdminOpen((o) => !o)}
          sx={{ minHeight: 40, px: 2.5 }}
        >
          <ListItemIcon sx={{ minWidth: 0, mr: 3, justifyContent: 'center' }}>
            <AdminPanelSettingsIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary="ADMIN"
            slotProps={{
              primary: {
                sx: {
                  fontSize: 11,
                  letterSpacing: '0.18em',
                  fontWeight: 700,
                  color: 'text.secondary',
                },
              },
            }}
          />
          {adminOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </ListItemButton>
        <Collapse in={adminOpen} timeout="auto" unmountOnExit>
          <List component="div" disablePadding>
            {ADMIN_NAV_ITEMS.map((item) =>
              renderNavItem(item.path, item.label, item.icon as IconName, { indent: true })
            )}
          </List>
        </Collapse>
      </>
    );
  };

  const renderDrawerContent = () => (
    <>
      <DrawerHeader>
        <IconButton onClick={isMobile ? onClose : onToggleCollapse}>
          {theme.direction === 'rtl' ? <ChevronRightIcon /> : <ChevronLeftIcon />}
        </IconButton>
      </DrawerHeader>
      <Divider />
      <List>
        {USER_NAV_ITEMS.map((item) =>
          renderNavItem(item.path, item.label, item.icon as IconName)
        )}
      </List>
      {renderAdminGroup()}
      {isAuthenticated && (
        <>
          <Divider sx={{ mt: 'auto' }} />
          <List>{renderNavItem(ROUTES.ACCOUNT, 'Account', 'AccountCircle')}</List>
        </>
      )}
    </>
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
