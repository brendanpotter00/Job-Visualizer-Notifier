import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GlobalAppBar } from '../../../components/layouts/GlobalAppBar';

describe('GlobalAppBar', () => {
  const mockProps = {
    open: false,
    onDrawerToggle: vi.fn(),
    drawerWidth: 240,
    isMobile: false,
  };

  describe('Rendering', () => {
    it('renders app title "1 Hour Jobs"', () => {
      render(<GlobalAppBar {...mockProps} />);
      expect(screen.getByText('1 Hour Jobs')).toBeInTheDocument();
    });

    it('renders hamburger menu button with MenuIcon', () => {
      render(<GlobalAppBar {...mockProps} />);
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeInTheDocument();
    });

    it('AppBar has fixed positioning', () => {
      const { container } = render(<GlobalAppBar {...mockProps} />);
      const appBar = container.querySelector('header');
      expect(appBar).toHaveClass('MuiAppBar-positionFixed');
    });
  });

  describe('Button Visibility', () => {
    it('menu button visible when drawer closed (desktop)', () => {
      render(<GlobalAppBar {...mockProps} open={false} isMobile={false} />);
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeVisible();
    });

    it('menu button hidden when drawer open (desktop)', () => {
      render(<GlobalAppBar {...mockProps} open={true} isMobile={false} />);
      const button = screen.getByLabelText('open drawer');
      expect(button).not.toBeVisible();
    });

    it('menu button always visible on mobile (drawer closed)', () => {
      render(<GlobalAppBar {...mockProps} open={false} isMobile={true} />);
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeVisible();
    });

    it('menu button always visible on mobile (drawer open)', () => {
      render(<GlobalAppBar {...mockProps} open={true} isMobile={true} />);
      const button = screen.getByLabelText('open drawer');
      expect(button).toBeVisible();
    });

    it('button has correct aria-label', () => {
      render(<GlobalAppBar {...mockProps} />);
      expect(screen.getByLabelText('open drawer')).toBeInTheDocument();
    });
  });

  describe('Interactions', () => {
    it('clicking button calls onDrawerToggle callback', async () => {
      const onDrawerToggle = vi.fn();
      const user = userEvent.setup();

      render(<GlobalAppBar {...mockProps} onDrawerToggle={onDrawerToggle} />);

      const button = screen.getByLabelText('open drawer');
      await user.click(button);

      expect(onDrawerToggle).toHaveBeenCalledTimes(1);
    });

    it('button is keyboard accessible', async () => {
      const onDrawerToggle = vi.fn();
      const user = userEvent.setup();

      render(<GlobalAppBar {...mockProps} onDrawerToggle={onDrawerToggle} />);

      const button = screen.getByLabelText('open drawer');
      button.focus();

      expect(button).toHaveFocus();

      await user.keyboard('{Enter}');
      expect(onDrawerToggle).toHaveBeenCalled();
    });
  });

  describe('Responsive Behavior', () => {
    it('AppBar full width when drawer closed', () => {
      const { container } = render(<GlobalAppBar {...mockProps} open={false} />);
      const appBar = container.querySelector('header');
      expect(appBar).not.toHaveStyle({ marginLeft: '240px' });
    });

    it('AppBar shifts right when drawer open', () => {
      const { container } = render(<GlobalAppBar {...mockProps} open={true} drawerWidth={240} />);
      const appBar = container.querySelector('header');
      expect(appBar).toHaveStyle({ marginLeft: '240px' });
    });

    it('props handling works correctly', () => {
      const customDrawerWidth = 300;
      const { container } = render(
        <GlobalAppBar {...mockProps} open={true} drawerWidth={customDrawerWidth} />
      );
      const appBar = container.querySelector('header');
      expect(appBar).toHaveStyle({ marginLeft: `${customDrawerWidth}px` });
    });
  });
});
