import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LoadingText } from '../../../components/shared/LoadingText';

/** The animated letter spans, in document order. */
function letterSpans(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>('.LoadingText-letter'));
}

describe('LoadingText', () => {
  describe('text', () => {
    it('renders every caption character in its own span, in order', () => {
      const { container } = render(<LoadingText text="Loading feedback" />);
      expect(letterSpans(container).map((s) => s.textContent)).toEqual(
        Array.from('Loadingfeedback')
      );
    });

    it('defaults to "Loading" when no text is passed', () => {
      const { container } = render(<LoadingText />);
      expect(screen.getByRole('progressbar')).toHaveAccessibleName('Loading');
      expect(
        letterSpans(container)
          .map((s) => s.textContent)
          .join('')
      ).toBe('Loading');
    });

    it.each([
      ['a unicode ellipsis', 'Loading feedback…'],
      ['three dots', 'Loading feedback...'],
      ['a spaced ellipsis', 'Loading feedback …'],
    ])('strips a trailing ellipsis written as %s', (_label, text) => {
      render(<LoadingText text={text} />);
      const progressbar = screen.getByRole('progressbar');
      expect(progressbar).toHaveAccessibleName('Loading feedback');
      expect(progressbar).toHaveTextContent(/^Loading feedback$/);
    });

    it('keeps an ellipsis that is not at the end', () => {
      render(<LoadingText text="Loading… almost there" />);
      expect(screen.getByRole('progressbar')).toHaveAccessibleName('Loading… almost there');
    });

    it('falls back to "Loading" when the text is only an ellipsis or blank', () => {
      const { rerender } = render(<LoadingText text="…" />);
      expect(screen.getByRole('progressbar')).toHaveAccessibleName('Loading');
      rerender(<LoadingText text="   " />);
      expect(screen.getByRole('progressbar')).toHaveAccessibleName('Loading');
    });
  });

  describe('spaces', () => {
    it('keeps the spaces between words as real (non-animated) text', () => {
      const { container } = render(<LoadingText text="Loading your companies" />);
      expect(screen.getByRole('progressbar')).toHaveTextContent(/^Loading your companies$/);
      // No letter span holds a space: inline-block would swallow it.
      expect(letterSpans(container).some((s) => /\s/.test(s.textContent ?? ''))).toBe(false);
    });

    it('keeps each word unbreakable so a narrow screen wraps only between words', () => {
      const { container } = render(<LoadingText text="Loading your companies" />);
      const words = Array.from(container.querySelectorAll('.LoadingText-word'));
      expect(words.map((w) => w.textContent)).toEqual(['Loading', 'your', 'companies']);
    });

    it('collapses runs of whitespace to single spaces', () => {
      render(<LoadingText text={'  Loading \n your   companies  '} />);
      expect(screen.getByRole('progressbar')).toHaveAccessibleName('Loading your companies');
    });
  });

  describe('accessibility', () => {
    it('is one indeterminate progressbar named by the whole caption', () => {
      render(<LoadingText text="Loading feedback…" />);
      const progressbar = screen.getByRole('progressbar', { name: 'Loading feedback' });
      expect(progressbar).not.toHaveAttribute('aria-valuenow');
    });

    it('hides the individual letters from assistive tech', () => {
      const { container } = render(<LoadingText text="Loading feedback" />);
      const letters = letterSpans(container);
      expect(letters.length).toBeGreaterThan(0);
      for (const letter of letters) {
        expect(letter.closest('[aria-hidden="true"]')).not.toBeNull();
      }
    });
  });

  describe('wave', () => {
    it('staggers neighbouring letters 0.1s apart', () => {
      const { container } = render(<LoadingText text="Loading" />);
      expect(letterSpans(container).map((s) => s.style.animationDelay)).toEqual([
        '-1.6s',
        '-1.5s',
        '-1.4s',
        '-1.3s',
        '-1.2s',
        '-1.1s',
        '-1.0s',
      ]);
    });

    it('counts the space between words, so the rhythm follows the width', () => {
      const { container } = render(<LoadingText text="ab cd" />);
      // a=0, b=1, (space)=2, c=3, d=4
      expect(letterSpans(container).map((s) => s.style.animationDelay)).toEqual([
        '-1.6s',
        '-1.5s',
        '-1.3s',
        '-1.2s',
      ]);
    });

    it('wraps the stagger every 16 characters, one full 1.6s cycle, so long text never stalls', () => {
      const { container } = render(<LoadingText text={'x'.repeat(40)} />);
      const delays = letterSpans(container).map((s) => s.style.animationDelay);
      expect(delays[16]).toBe(delays[0]);
      expect(delays[33]).toBe(delays[1]);
      // Every letter is already moving on the first frame: no positive delay.
      expect(delays.every((d) => d.startsWith('-'))).toBe(true);
    });
  });
});
