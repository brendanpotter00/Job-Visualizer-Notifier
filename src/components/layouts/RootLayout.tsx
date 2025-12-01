import { useState, useEffect } from 'react';
import { styled, useTheme } from '@mui/material/styles';
import Box from '@mui/material/Box';
import useMediaQuery from '@mui/material/useMediaQuery';
import { Outlet } from 'react-router-dom';
import { GlobalAppBar } from './GlobalAppBar';
import { NavigationDrawer } from './NavigationDrawer';
import { AppFooter } from './AppFooter';

const DRAWER_WIDTH = 240;
export const MINI_DRAWER_WIDTH = 65; // Match NavigationDrawer's calculated width

/**
 * Drawer header spacer to push content below app bar
 */
const DrawerHeader = styled('div')(({ theme }) => ({
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'flex-end',
  padding: theme.spacing(0, 1),
  ...theme.mixins.toolbar,
}));

/**
 * Root layout component for the entire application
 *
 * Features:
 * - Global app bar with drawer toggle
 * - Responsive navigation drawer (persistent on desktop, temporary on mobile)
 * - Main content area for page rendering via Outlet
 * - Global footer
 *
 * State Management:
 * - Drawer state managed locally (no persistence)
 * - Open by default on desktop, closed on mobile
 * - Mobile: <900px (md breakpoint)
 *
 * @returns Root layout with drawer navigation
 */
export function RootLayout() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  // Drawer state: open by default on desktop, closed on mobile
  // No persistence - resets on page refresh
  const [drawerOpen, setDrawerOpen] = useState(!isMobile);

  // Auto-sync drawer state when viewport size changes
  useEffect(() => {
    setDrawerOpen(!isMobile);
  }, [isMobile]);

  const handleDrawerToggle = () => {
    setDrawerOpen(!drawerOpen);
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
  };

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', flexDirection: 'column' }}>
      <GlobalAppBar
        open={drawerOpen && !isMobile}
        onDrawerToggle={handleDrawerToggle}
        drawerWidth={DRAWER_WIDTH}
      />
      <NavigationDrawer
        open={drawerOpen}
        onClose={handleDrawerClose}
        onToggleCollapse={handleDrawerToggle}
        drawerWidth={DRAWER_WIDTH}
        isMobile={isMobile}
      />
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          display: 'flex',
          flexDirection: 'column',
          // 💡 Permanent drawer: account for full vs mini width
          // Temporary (mobile): no margin, drawer just overlays
          ml: !isMobile ? (drawerOpen ? `${DRAWER_WIDTH}px` : `${MINI_DRAWER_WIDTH}px`) : 0,

          transition: theme.transitions.create('margin', {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.leavingScreen,
          }),
        }}
      >
        <DrawerHeader />
        <Box sx={{ flex: 1 }}>
          <Outlet />
        </Box>
        <AppFooter />
      </Box>
    </Box>
  );
}
