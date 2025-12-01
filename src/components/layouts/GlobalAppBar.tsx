import { styled } from '@mui/material/styles';
import MuiAppBar, { AppBarProps as MuiAppBarProps } from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import MenuIcon from '@mui/icons-material/Menu';

/**
 * Props for the GlobalAppBar component
 */
interface GlobalAppBarProps {
  /** Whether the drawer is currently open */
  open: boolean;
  /** Callback to toggle the drawer */
  onDrawerToggle: () => void;
  /** Drawer width for calculating margins */
  drawerWidth: number;
}

interface AppBarProps extends MuiAppBarProps {
  open?: boolean;
  drawerWidth?: number;
}

/**
 * Styled MUI AppBar that shifts when drawer opens
 */
const AppBar = styled(MuiAppBar, {
  shouldForwardProp: (prop) => prop !== 'open' && prop !== 'drawerWidth',
})<AppBarProps>(({ theme, open, drawerWidth = 240 }) => ({
  zIndex: theme.zIndex.drawer + 1,
  transition: theme.transitions.create(['width', 'margin'], {
    easing: theme.transitions.easing.sharp,
    duration: theme.transitions.duration.leavingScreen,
  }),
  ...(open && {
    marginLeft: drawerWidth,
    width: `calc(100% - ${drawerWidth}px)`,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  }),
}));

/**
 * Global application header with app name and drawer toggle
 *
 * Features:
 * - Displays "1 Hour Jobs" title
 * - Hamburger menu button to toggle drawer
 * - Shifts right when drawer opens (desktop only)
 *
 * @param props - Component props
 * @returns Global app bar component
 */
export function GlobalAppBar({ open, onDrawerToggle, drawerWidth }: GlobalAppBarProps) {
  return (
    <AppBar position="fixed" open={open} drawerWidth={drawerWidth}>
      <Toolbar>
        <IconButton
          color="inherit"
          aria-label="open drawer"
          onClick={onDrawerToggle}
          edge="start"
          sx={[
            {
              marginRight: 5,
            },
            open && { display: 'none' },
          ]}
        >
          <MenuIcon />
        </IconButton>
        <Typography variant="h6" noWrap component="div">
          1 Hour Jobs
        </Typography>
      </Toolbar>
    </AppBar>
  );
}
