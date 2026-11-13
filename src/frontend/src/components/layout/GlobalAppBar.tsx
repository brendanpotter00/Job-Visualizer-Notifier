import { APP_TITLE } from '../../config/constants';
import { keyframes } from '@mui/material/styles';
import AppBar from '@mui/material/AppBar';
import Box from '@mui/material/Box';
import Toolbar from '@mui/material/Toolbar';
import { Link as RouterLink } from 'react-router-dom';
import { UserMenu } from './UserMenu';
import { SidebarToggleButton } from './SidebarToggleButton';

const recBlink = keyframes`
  0%, 55% { opacity: 1; }
  60%, 100% { opacity: 0.25; }
`;

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
          to="/"
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
          <Box
            component="span"
            aria-hidden
            sx={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '22px' }}
          >
            <span>1s</span>
            <Box
              component="span"
              sx={{
                width: '7px',
                height: '7px',
                borderRadius: '50%',
                background: '#2F8F3F',
                boxShadow: '0 0 8px rgba(47,143,63,0.6)',
                display: 'inline-block',
                animation: `${recBlink} 2.2s ease-in-out infinite`,
                '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
              }}
            />
          </Box>
        </Box>
        <Box sx={{ flexGrow: 1 }} />
        <UserMenu />
      </Toolbar>
    </AppBar>
  );
}
