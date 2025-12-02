import { styled, useTheme, Theme, CSSObject } from '@mui/material/styles';
import MuiDrawer from '@mui/material/Drawer';
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
import BusinessIcon from '@mui/icons-material/Business';
import ScheduleIcon from '@mui/icons-material/Schedule';
import InfoIcon from '@mui/icons-material/Info';
import { useNavigate, useLocation } from 'react-router-dom';
import { NAV_ITEMS } from '../../config/routes';

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

/**
 * Mixin for opened drawer state
 */
const openedMixin = (theme: Theme, drawerWidth: number): CSSObject => ({
  width: drawerWidth,
  transition: theme.transitions.create('width', {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.enteringScreen,
  }),
  overflowX: 'hidden',
});

/**
 * Mixin for closed drawer state (collapsed to icons only)
 */
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

/**
 * Drawer header with collapse button
 */
const DrawerHeader = styled('div')(({ theme }) => ({
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'flex-end',
  padding: theme.spacing(0, 1),
  ...theme.mixins.toolbar,
}));

/**
 * Styled drawer for permanent (desktop) variant only
 */
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

/**
 * Map icon names to MUI icon components
 */
type IconName = 'Business' | 'Schedule' | 'Info';
const iconMap: Record<IconName, React.ComponentType> = {
  Business: BusinessIcon,
  Schedule: ScheduleIcon,
  Info: InfoIcon,
};

/**
 * Navigation drawer with page links
 *
 * Features:
 * - Desktop (≥900px): Persistent drawer with collapse support
 * - Mobile (<900px): Temporary drawer that closes on navigation
 * - Highlights active route
 * - Icon-only mode when collapsed (desktop only)
 *
 * Implementation:
 * - Uses separate JSX branches for mobile vs desktop for clarity
 * - Mobile: MUI Drawer with temporary variant
 * - Desktop: Custom PermanentDrawer with collapse animations
 *
 * @param props - Component props
 * @returns Navigation drawer component
 */
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

  const handleNavigate = (path: string) => {
    navigate(path);
    // Close drawer on mobile after navigation
    if (isMobile) {
      onClose();
    }
  };

  /**
   * Renders the drawer content (header, divider, nav items)
   * Extracted to avoid duplication between mobile and desktop drawers
   */
  const renderDrawerContent = () => (
    <>
      <DrawerHeader>
        <IconButton onClick={isMobile ? onClose : onToggleCollapse}>
          {theme.direction === 'rtl' ? <ChevronRightIcon /> : <ChevronLeftIcon />}
        </IconButton>
      </DrawerHeader>
      <Divider />
      <List>
        {NAV_ITEMS.map((item) => {
          const Icon = iconMap[item.icon as IconName];
          const isActive = location.pathname === item.path;

          return (
            <ListItem key={item.path} disablePadding sx={{ display: 'block' }}>
              <ListItemButton
                onClick={() => handleNavigate(item.path)}
                sx={[
                  {
                    minHeight: 48,
                    px: 2.5,
                  },
                  open
                    ? {
                        justifyContent: 'initial',
                      }
                    : {
                        justifyContent: 'center',
                      },
                  isActive && {
                    bgcolor: 'action.selected',
                  },
                ]}
              >
                <Tooltip title={item.label} placement="right" arrow disableHoverListener={open}>
                  <ListItemIcon
                    sx={[
                      {
                        minWidth: 0,
                        justifyContent: 'center',
                      },
                      open
                        ? {
                            mr: 3,
                          }
                        : {
                            mr: 'auto',
                          },
                    ]}
                  >
                    <Icon />
                  </ListItemIcon>
                </Tooltip>
                <ListItemText
                  primary={item.label}
                  sx={[
                    open
                      ? {
                          opacity: 1,
                        }
                      : {
                          opacity: 0,
                        },
                  ]}
                />
              </ListItemButton>
            </ListItem>
          );
        })}
      </List>
    </>
  );

  // Mobile: temporary drawer with standard MUI behavior
  if (isMobile) {
    return (
      <MuiDrawer
        variant="temporary"
        open={open}
        onClose={onClose}
        ModalProps={{
          keepMounted: true, // Better mobile performance
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

  // Desktop: permanent drawer with custom collapse behavior
  return (
    <PermanentDrawer variant="permanent" open={open} drawerWidth={drawerWidth}>
      {renderDrawerContent()}
    </PermanentDrawer>
  );
}
