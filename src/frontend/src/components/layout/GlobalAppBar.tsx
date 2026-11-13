import { APP_TITLE } from '../../config/constants';
import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import Toolbar from '@mui/material/Toolbar';
import { Link as RouterLink } from 'react-router-dom';
import { UserMenu } from './UserMenu';
import { ROUTES } from '../../config/routes';
import { OneSecondMark } from '../shared/OneSecondMark';
import { SidebarToggleButton } from './SidebarToggleButton';

/**
 * Props for the GlobalAppBar component
 */
interface GlobalAppBarProps {
  /** Whether the drawer is currently open */
  open: boolean;
  /** Callback to toggle the drawer */
  onDrawerToggle: () => void;
}

/**
 * Global application header with app name and drawer toggle
 *
 * Features:
 * - Displays app title
 * - Sidebar toggle button
 * - Spans the full width above the drawer
 *
 * @param props - Component props
 * @returns Global app bar component
 */
export function GlobalAppBar({ open, onDrawerToggle }: GlobalAppBarProps) {
  return (
    <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
      <Toolbar>
        <Box component="span" sx={{ mr: 2, display: 'inline-flex' }}>
          <SidebarToggleButton open={open} onClick={onDrawerToggle} />
        </Box>
        <Box
          component={RouterLink}
          to={ROUTES.RECENT_JOBS}
          aria-label={APP_TITLE}
          sx={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '14px',
            color: '#F2EEE9',
            textDecoration: 'none',
            fontFamily:
              '"Infra Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
            fontWeight: 700,
            letterSpacing: '-0.03em',
            lineHeight: 1,
          }}
        >
          <Box
            component="span"
            sx={{ fontSize: '20px', display: { xs: 'none', md: 'inline' } }}
          >
            {APP_TITLE}
          </Box>
          <OneSecondMark />
        </Box>
        <Box sx={{ flexGrow: 1 }} />
        <UserMenu />
      </Toolbar>
    </AppBar>
  );
}
