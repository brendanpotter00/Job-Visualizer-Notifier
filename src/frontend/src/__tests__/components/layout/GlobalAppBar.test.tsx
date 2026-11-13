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
  };

  const toggle = () => screen.getByRole('button', { name: 'Toggle sidebar' });

  describe('Rendering', () => {
    it(`renders brand logo with "${APP_TITLE}" accessible label`, () => {
      renderAppBar(mockProps);
      const logo = screen.getByLabelText(APP_TITLE);
      expect(logo).toBeInTheDocument();
      expect(logo).toHaveTextContent('1s');
      expect(logo).toHaveAttribute('href', '/');
    });

    it('renders the sidebar toggle as the first control in the toolbar', () => {
      renderAppBar(mockProps);
      const toolbar = toggle().closest('.MuiToolbar-root') as HTMLElement;
      expect(toolbar).not.toBeNull();
      // First focusable thing in the bar: the toggle precedes the logo link.
      const logo = screen.getByLabelText(APP_TITLE);
      expect(
        toggle().compareDocumentPosition(logo) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    });

    it('AppBar has fixed positioning', () => {
      const { container } = renderAppBar(mockProps);
      const appBar = container.querySelector('header');
      expect(appBar).toHaveClass('MuiAppBar-positionFixed');
    });
  });

  describe('Sidebar toggle', () => {
    /**
     * The toggle used to exist only while the drawer was closed (a hamburger
     * here) and moved to a chevron at the drawer edge once open. It is now ONE
     * button that is always present, in both states.
     */
    it.each([false, true])('is visible whether the drawer is open or not (open=%s)', (open) => {
      renderAppBar({ ...mockProps, open });
      expect(toggle()).toBeVisible();
    });

    it.each([
      [false, 'false'],
      [true, 'true'],
    ])('reports the drawer state through aria-expanded (open=%s)', (open, expected) => {
      renderAppBar({ ...mockProps, open });
      expect(toggle()).toHaveAttribute('aria-expanded', expected);
      expect(toggle()).toHaveAttribute('aria-controls', 'app-navigation');
    });

    it('draws the sidebar glyph, not a hamburger or chevron', () => {
      renderAppBar(mockProps);
      expect(screen.queryByTestId('MenuIcon')).not.toBeInTheDocument();
      expect(screen.queryByTestId('ChevronLeftIcon')).not.toBeInTheDocument();
      expect(toggle().querySelector('svg')).not.toBeNull();
    });
  });

  describe('Interactions', () => {
    it('clicking the toggle calls onDrawerToggle', async () => {
      const onDrawerToggle = vi.fn();
      const user = userEvent.setup();

      renderAppBar({ ...mockProps, onDrawerToggle });
      await user.click(toggle());

      expect(onDrawerToggle).toHaveBeenCalledTimes(1);
    });

    it('the toggle is keyboard accessible', async () => {
      const onDrawerToggle = vi.fn();
      const user = userEvent.setup();

      renderAppBar({ ...mockProps, onDrawerToggle });
      toggle().focus();
      expect(toggle()).toHaveFocus();

      await user.keyboard('{Enter}');
      expect(onDrawerToggle).toHaveBeenCalled();
    });
  });

  describe('Layout', () => {
    /**
     * The bar spans the full width in both states — the drawer is clipped
     * beneath it — so nothing in it (toggle, logo) moves when the drawer opens.
     */
    it.each([false, true])('never shifts right (open=%s)', (open) => {
      const { container } = renderAppBar({ ...mockProps, open });
      const appBar = container.querySelector('header');
      expect(appBar).not.toHaveStyle({ marginLeft: '240px' });
      expect(appBar?.style.marginLeft ?? '').toBe('');
    });
  });
});
