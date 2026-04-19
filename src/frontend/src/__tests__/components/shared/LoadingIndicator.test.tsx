import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LoadingIndicator, LoadingState } from '../../../components/shared/LoadingIndicator';

describe('LoadingIndicator', () => {
  describe('Default rendering', () => {
    it('renders a progressbar with the default size', () => {
      render(<LoadingIndicator />);
      const progressbar = screen.getByRole('progressbar');
      expect(progressbar).toBeInTheDocument();
      const svg = progressbar.querySelector('svg');
      expect(svg).toHaveAttribute('viewBox', '22 22 44 44');
    });

    it('applies the default minHeight of 200 when neither minHeight nor fullPage is set', () => {
      const { container } = render(<LoadingIndicator />);
      const box = container.firstChild as HTMLElement;
      expect(box).toHaveStyle({ minHeight: '200px' });
    });

    it('does not render a caption Typography when caption is omitted', () => {
      render(<LoadingIndicator />);
      expect(screen.queryByText(/./)).toBeNull();
    });
  });

  describe('caption prop', () => {
    it('renders the caption text under the spinner', () => {
      render(<LoadingIndicator caption="Loading jobs..." />);
      expect(screen.getByText('Loading jobs...')).toBeInTheDocument();
      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });

    it('uses body1 Typography (zero-visual-change vs CompaniesPageContent)', () => {
      render(<LoadingIndicator caption="Workday source requires more loading time..." />);
      const caption = screen.getByText('Workday source requires more loading time...');
      expect(caption).toHaveClass('MuiTypography-body1');
    });

    it('does not render the caption when caption is empty string', () => {
      const { container } = render(<LoadingIndicator caption="" />);
      expect(container.querySelector('.MuiTypography-root')).toBeNull();
    });
  });

  describe('fullPage prop', () => {
    it('applies minHeight: 100vh when fullPage is true', () => {
      const { container } = render(<LoadingIndicator fullPage />);
      const box = container.firstChild as HTMLElement;
      expect(box).toHaveStyle({ minHeight: '100vh' });
    });

    it('explicit minHeight overrides fullPage default', () => {
      const { container } = render(<LoadingIndicator fullPage minHeight={300} />);
      const box = container.firstChild as HTMLElement;
      expect(box).toHaveStyle({ minHeight: '300px' });
    });
  });

  describe('minHeight prop', () => {
    it('accepts a numeric minHeight', () => {
      const { container } = render(<LoadingIndicator minHeight={150} />);
      const box = container.firstChild as HTMLElement;
      expect(box).toHaveStyle({ minHeight: '150px' });
    });

    it('accepts a string minHeight', () => {
      const { container } = render(<LoadingIndicator minHeight="50vh" />);
      const box = container.firstChild as HTMLElement;
      expect(box).toHaveStyle({ minHeight: '50vh' });
    });
  });

  describe('size prop', () => {
    it('forwards size to CircularProgress', () => {
      render(<LoadingIndicator size={60} />);
      const progressbar = screen.getByRole('progressbar');
      expect(progressbar).toHaveStyle({ width: '60px', height: '60px' });
    });
  });

  describe('LoadingState alias', () => {
    it('is the same reference as LoadingIndicator (export-as rename)', () => {
      expect(LoadingState).toBe(LoadingIndicator);
    });

    it('renders identically to LoadingIndicator for the same props', () => {
      const a = render(<LoadingIndicator caption="x" fullPage size={50} />);
      const aHtml = a.container.innerHTML;
      a.unmount();

      const b = render(<LoadingState caption="x" fullPage size={50} />);
      expect(b.container.innerHTML).toBe(aHtml);
    });
  });
});
