import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppFooter } from '../../../components/layouts/AppFooter';

describe('AppFooter', () => {
  describe('Rendering', () => {
    it('renders footer with semantic footer element', () => {
      const { container } = render(<AppFooter />);
      const footer = container.querySelector('footer');
      expect(footer).toBeInTheDocument();
    });

    it('displays author name "Brendan Potter"', () => {
      render(<AppFooter />);
      expect(screen.getByText('Brendan Potter')).toBeInTheDocument();
    });

    it('displays "Made by" text', () => {
      render(<AppFooter />);
      expect(screen.getByText(/Made by/i)).toBeInTheDocument();
    });

    it('renders link to LinkedIn profile', () => {
      render(<AppFooter />);
      const link = screen.getByRole('link', { name: 'Brendan Potter' });
      expect(link).toBeInTheDocument();
    });
  });

  describe('Link Behavior', () => {
    it('link has correct LinkedIn URL', () => {
      render(<AppFooter />);
      const link = screen.getByRole('link', { name: 'Brendan Potter' });
      expect(link).toHaveAttribute('href', 'https://www.linkedin.com/in/brendan-potter00/');
    });

    it('link opens in new tab', () => {
      render(<AppFooter />);
      const link = screen.getByRole('link', { name: 'Brendan Potter' });
      expect(link).toHaveAttribute('target', '_blank');
    });

    it('link has security attributes', () => {
      render(<AppFooter />);
      const link = screen.getByRole('link', { name: 'Brendan Potter' });
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    });
  });

  describe('Styling', () => {
    it('has border-top divider', () => {
      const { container } = render(<AppFooter />);
      const footer = container.querySelector('footer');
      const styles = window.getComputedStyle(footer as Element);
      expect(styles.borderTopWidth).not.toBe('0px');
    });

    it('text is centered', () => {
      const { container } = render(<AppFooter />);
      const footer = container.querySelector('footer');
      expect(footer).toHaveStyle({ textAlign: 'center' });
    });
  });
});
