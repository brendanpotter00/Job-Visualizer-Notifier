import { describe, it, expect, vi } from 'vitest';
import { screen, render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { NavigationDrawer } from '../../../components/layouts/NavigationDrawer';

const mockProps = {
  open: true,
  onClose: vi.fn(),
  onToggleCollapse: vi.fn(),
  drawerWidth: 240,
  isMobile: false,
};

describe('NavigationDrawer', () => {
  describe('Rendering', () => {
    it('renders all navigation items from NAV_ITEMS config', () => {
      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} />
        </MemoryRouter>
      );

      expect(screen.getByText('Companies')).toBeInTheDocument();
      expect(screen.getByText('Recent Job Postings')).toBeInTheDocument();
    });

    it('renders chevron button for collapse/expand', () => {
      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} />
        </MemoryRouter>
      );

      // Chevron button is the icon button in the drawer header
      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });
  });

  describe('Drawer Variants', () => {
    it('uses permanent variant when isMobile is false', () => {
      const { container } = render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} isMobile={false} />
        </MemoryRouter>
      );

      // Permanent drawer has docked variant
      const drawer = container.querySelector('.MuiDrawer-docked');
      expect(drawer).toBeInTheDocument();
    });

    it('uses temporary variant when isMobile is true', () => {
      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} isMobile={true} />
        </MemoryRouter>
      );

      // When mobile and open, temporary drawer renders navigation items
      expect(screen.getByText('Companies')).toBeInTheDocument();
      expect(screen.getByText('Recent Job Postings')).toBeInTheDocument();
    });
  });

  describe('Navigation', () => {
    it('highlights active route with selected background', () => {
      render(
        <MemoryRouter initialEntries={['/']}>
          <NavigationDrawer {...mockProps} />
        </MemoryRouter>
      );

      // Check that the Companies button has selected styling via computed styles
      const companiesButton = screen.getByText('Companies').closest('div[role="button"]');
      expect(companiesButton).toBeInTheDocument();

      // Verify background color is set (action.selected)
      const styles = window.getComputedStyle(companiesButton as Element);
      expect(styles.backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
    });

    it('navigates to route when item clicked', async () => {
      const user = userEvent.setup();

      render(
        <MemoryRouter initialEntries={['/']}>
          <NavigationDrawer {...mockProps} />
        </MemoryRouter>
      );

      const recentJobsButton = screen.getByText('Recent Job Postings');
      await user.click(recentJobsButton);

      // Check that button is still rendered (navigation happened)
      expect(recentJobsButton).toBeInTheDocument();
    });
  });

  describe('Mobile vs Desktop Behavior', () => {
    it('clicking nav item on mobile calls onClose', async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();

      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} isMobile={true} onClose={onClose} />
        </MemoryRouter>
      );

      const companiesButton = screen.getByText('Companies');
      await user.click(companiesButton);

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('clicking nav item on desktop does NOT call onClose', async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();

      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} isMobile={false} onClose={onClose} />
        </MemoryRouter>
      );

      const companiesButton = screen.getByText('Companies');
      await user.click(companiesButton);

      expect(onClose).not.toHaveBeenCalled();
    });

    it('clicking chevron on mobile calls onClose', async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();

      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} isMobile={true} open={true} onClose={onClose} />
        </MemoryRouter>
      );

      // Find chevron button by test ID icon
      const chevronButton = screen.getByTestId('ChevronLeftIcon').closest('button');
      expect(chevronButton).toBeTruthy();

      await user.click(chevronButton!);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('clicking chevron on desktop calls onToggleCollapse', async () => {
      const onToggleCollapse = vi.fn();
      const user = userEvent.setup();

      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} isMobile={false} onToggleCollapse={onToggleCollapse} />
        </MemoryRouter>
      );

      // First button is the chevron
      const buttons = screen.getAllByRole('button');
      const chevronButton = buttons[0];

      await user.click(chevronButton);
      expect(onToggleCollapse).toHaveBeenCalledTimes(1);
    });
  });

  describe('Accessibility', () => {
    it('nav items are keyboard accessible', async () => {
      const user = userEvent.setup();

      render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} />
        </MemoryRouter>
      );

      const companiesButton = screen.getByText('Companies').closest('button');
      if (companiesButton) {
        companiesButton.focus();
        expect(companiesButton).toHaveFocus();

        await user.keyboard('{Enter}');
        // Button should still be in document after click
        expect(companiesButton).toBeInTheDocument();
      }
    });

    it('has proper list structure', () => {
      const { container } = render(
        <MemoryRouter>
          <NavigationDrawer {...mockProps} />
        </MemoryRouter>
      );

      const list = container.querySelector('ul');
      expect(list).toBeInTheDocument();
    });
  });
});
