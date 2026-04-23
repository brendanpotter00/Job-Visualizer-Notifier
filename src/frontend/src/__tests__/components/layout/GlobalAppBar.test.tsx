import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { GlobalAppBar } from '../../../components/layout/GlobalAppBar.tsx';
import { APP_TITLE } from '../../../config/constants';

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: false,
    isAuthenticated: false,
    isLoading: false,
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
  }),
}));

function renderAppBar(props = {}) {
  const defaultProps = {
    open: false,
    onDrawerToggle: vi.fn(),
    drawerWidth: 240,
    isMobile: false,
  };
  return render(
    <MemoryRouter>
      <GlobalAppBar {...defaultProps} {...props} />
    </MemoryRouter>
  );
}

describe('GlobalAppBar', () => {
  const mockProps = {
    open: false,
    onDrawerToggle: vi.fn(),
    drawerWidth: 240,
    isMobile: false,
  };

  describe('Rendering', () => {
    it(`renders brand logo with "${APP_TITLE}" accessible label`, () => {
      renderAppBar(mockProps);
      const logo = screen.getByLabelText(APP_TITLE);
      expect(logo).toBeInTheDocument();
      expect(logo).toHaveTextContent('1s');
      expect(logo).toHaveAttribute('href', '/');
    });

    it('renders hamburger menu button with MenuIcon', () => {
      renderAppBar(mockProps);
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeInTheDocument();
    });

    it('AppBar has fixed positioning', () => {
      const { container } = renderAppBar(mockProps);
      const appBar = container.querySelector('header');
      expect(appBar).toHaveClass('MuiAppBar-positionFixed');
    });
  });

  describe('Button Visibility', () => {
    it('menu button visible when drawer closed (desktop)', () => {
      renderAppBar({ ...mockProps, open: false, isMobile: false });
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeVisible();
    });

    it('menu button hidden when drawer open (desktop)', () => {
      renderAppBar({ ...mockProps, open: true, isMobile: false });
      const button = screen.getByLabelText('open drawer');
      expect(button).not.toBeVisible();
    });

    it('menu button always visible on mobile (drawer closed)', () => {
      renderAppBar({ ...mockProps, open: false, isMobile: true });
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeVisible();
    });

    it('menu button always visible on mobile (drawer open)', () => {
      renderAppBar({ ...mockProps, open: true, isMobile: true });
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeVisible();
    });

    it('button has correct aria-label', () => {
      renderAppBar(mockProps);
      expect(screen.getByLabelText('open drawer')).toBeInTheDocument();
    });
  });

  describe('Interactions', () => {
    it('clicking button calls onDrawerToggle callback', async () => {
      const onDrawerToggle = vi.fn();
      const user = userEvent.setup();

      renderAppBar({ ...mockProps, onDrawerToggle });

      const button = screen.getByLabelText('open drawer');
      await user.click(button);

      expect(onDrawerToggle).toHaveBeenCalledTimes(1);
    });

    it('button is keyboard accessible', async () => {
      const onDrawerToggle = vi.fn();
      const user = userEvent.setup();

      renderAppBar({ ...mockProps, onDrawerToggle });

      const button = screen.getByLabelText('open drawer');
      button.focus();

      expect(button).toHaveFocus();

      await user.keyboard('{Enter}');
      expect(onDrawerToggle).toHaveBeenCalled();
    });
  });

  describe('Responsive Behavior', () => {
    it('AppBar full width when drawer closed', () => {
      const { container } = renderAppBar({ ...mockProps, open: false });
      const appBar = container.querySelector('header');
      expect(appBar).not.toHaveStyle({ marginLeft: '240px' });
    });

    it('AppBar shifts right when drawer open', () => {
      const { container } = renderAppBar({ ...mockProps, open: true, drawerWidth: 240 });
      const appBar = container.querySelector('header');
      expect(appBar).toHaveStyle({ marginLeft: '240px' });
    });

    it('props handling works correctly', () => {
      const customDrawerWidth = 300;
      const { container } = renderAppBar({
        ...mockProps,
        open: true,
        drawerWidth: customDrawerWidth,
      });
      const appBar = container.querySelector('header');
      expect(appBar).toHaveStyle({ marginLeft: `${customDrawerWidth}px` });
    });
  });
});
