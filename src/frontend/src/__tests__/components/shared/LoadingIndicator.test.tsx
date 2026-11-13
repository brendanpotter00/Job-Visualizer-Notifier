import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LoadingIndicator, LoadingState } from '../../../components/shared/LoadingIndicator';

describe('LoadingIndicator', () => {
  describe('Default rendering', () => {
    it('renders a progressbar named "Loading" and no spinner', () => {
      const { container } = render(<LoadingIndicator />);
      expect(screen.getByRole('progressbar')).toHaveAccessibleName('Loading');
      // The wave replaced the spinner outright: no CircularProgress SVG anywhere.
      expect(container.querySelector('svg')).toBeNull();
      expect(container.querySelector('.MuiCircularProgress-root')).toBeNull();
    });

    it('waves the default word when no caption is passed', () => {
      render(<LoadingIndicator />);
      expect(screen.getByRole('progressbar')).toHaveTextContent(/^Loading$/);
    });

    it('applies the default minHeight of 200 when neither minHeight nor fullPage is set', () => {
      const { container } = render(<LoadingIndicator />);
      const box = container.firstChild as HTMLElement;
      expect(box).toHaveStyle({ minHeight: '200px' });
    });
  });

  describe('caption prop', () => {
    it('waves the caption, with the trailing ellipsis dropped', () => {
      render(<LoadingIndicator caption="Loading jobs..." />);
      const progressbar = screen.getByRole('progressbar');
      expect(progressbar).toHaveAccessibleName('Loading jobs');
      expect(progressbar).toHaveTextContent(/^Loading jobs$/);
    });

    it('uses body1 Typography (the theme body font and size)', () => {
      render(<LoadingIndicator caption="Loading feedback…" />);
      expect(screen.getByRole('progressbar')).toHaveClass('MuiTypography-body1');
    });

    it('falls back to "Loading" when the caption is an empty string', () => {
      render(<LoadingIndicator caption="" />);
      expect(screen.getByRole('progressbar')).toHaveAccessibleName('Loading');
    });
  });

  describe('fullPage prop', () => {
    it('applies minHeight: 100vh when fullPage is true', () => {
      const { container } = render(<LoadingIndicator fullPage />);
      const box = container.firstChild as HTMLElement;
      expect(box).toHaveStyle({ minHeight: '100vh' });
    });

    // The discriminated-union prop type forbids passing `minHeight` alongside
    // `fullPage: true`, so there is no runtime precedence case to cover here.
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

  describe('LoadingState alias', () => {
    it('is the same reference as LoadingIndicator (export-as rename)', () => {
      expect(LoadingState).toBe(LoadingIndicator);
    });

    it('renders identically to LoadingIndicator for the same props', () => {
      const a = render(<LoadingIndicator caption="x" fullPage />);
      const aHtml = a.container.innerHTML;
      a.unmount();

      const b = render(<LoadingState caption="x" fullPage />);
      expect(b.container.innerHTML).toBe(aHtml);
    });
  });
});
