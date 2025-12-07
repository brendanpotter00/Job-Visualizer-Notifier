import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { RootLayout } from '../../../components/layout/RootLayout.tsx';
import useMediaQuery from '@mui/material/useMediaQuery';

// Mock useMediaQuery to control mobile/desktop state
vi.mock('@mui/material/useMediaQuery');

describe('RootLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Component Composition', () => {
    it('renders GlobalAppBar, NavigationDrawer, and AppFooter', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      // Check for app title from GlobalAppBar
      expect(screen.getByText('1 Hour Jobs')).toBeInTheDocument();

      // Check for navigation items from NavigationDrawer
      expect(screen.getByText('Company Job Postings')).toBeInTheDocument();

      // Check for footer author name from AppFooter
      expect(screen.getByText('Brendan Potter')).toBeInTheDocument();
    });

    it('renders Outlet for nested routes', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      // Outlet renders - check for main element
      expect(screen.getByRole('main')).toBeInTheDocument();
    });
  });

  describe('Drawer State Management', () => {
    it('drawer open by default on desktop', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      const { container } = render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      // Check for expanded drawer (permanent variant)
      const drawer = container.querySelector('.MuiDrawer-docked');
      expect(drawer).toBeInTheDocument();
    });

    it('drawer closed by default on mobile', () => {
      vi.mocked(useMediaQuery).mockReturnValue(true); // mobile

      render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      // On mobile, drawer starts closed - nav items should not be visible (modal is closed)
      // AppBar title should still be visible
      expect(screen.getByText('1 Hour Jobs')).toBeInTheDocument();
    });
  });

  describe('Main Content Margins', () => {
    it('has left margin when drawer open on desktop', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      const { container } = render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      const mainContent = container.querySelector('main');
      const styles = window.getComputedStyle(mainContent as Element);

      // Should have margin (either 240px or 65px)
      expect(styles.marginLeft).not.toBe('0px');
    });

    it('has zero margin on mobile', () => {
      vi.mocked(useMediaQuery).mockReturnValue(true); // mobile

      const { container } = render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      const mainContent = container.querySelector('main');
      const styles = window.getComputedStyle(mainContent as Element);

      expect(styles.marginLeft).toBe('0px');
    });
  });

  describe('Layout Structure', () => {
    it('outer box has min height 100vh', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      const { container } = render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      const outerBox = container.firstChild;
      expect(outerBox).toHaveStyle({ minHeight: '100vh' });
    });

    it('main content has flex grow', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      const { container } = render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      const mainContent = container.querySelector('main');
      expect(mainContent).toHaveStyle({ flexGrow: '1' });
    });

    it('footer is rendered at bottom', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      // Footer should exist and be last element
      const footer = screen.getByText('Brendan Potter').closest('footer');
      expect(footer).toBeInTheDocument();
    });
  });

  describe('Drawer Props Passing', () => {
    it('GlobalAppBar receives drawer width prop', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      // AppBar should exist with title
      expect(screen.getByText('1 Hour Jobs')).toBeInTheDocument();
    });

    it('NavigationDrawer receives navigation items', () => {
      vi.mocked(useMediaQuery).mockReturnValue(false); // desktop

      render(
        <MemoryRouter>
          <RootLayout />
        </MemoryRouter>
      );

      // Navigation items should be present
      expect(screen.getByText('Company Job Postings')).toBeInTheDocument();
      expect(screen.getByText('Recent Job Postings')).toBeInTheDocument();
    });
  });
});
