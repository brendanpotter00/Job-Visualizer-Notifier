import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material/styles';
import { MetricCard } from '../../../../components/companies-page/MetricsDashboard/MetricCard';
import { theme } from '../../../../config/theme';
import { RESPONSIVE } from '../../../../config/responsive';

/**
 * MetricCard is a pure presentational component. We wrap it in the app theme so
 * the value Typography resolves the `h3` variant.
 *
 * Guards the `dense` branch (IMP-1): the dense font-size override is applied as
 * an MUI responsive `{ xs, sm }` sx object, which Emotion serializes into
 * `@media` rules on the element's own class. jsdom's `getComputedStyle` only
 * reports the base rule (which equals the theme default), so a regression
 * dropping the dense override is invisible to computed-style assertions. We
 * therefore inspect the actual emitted CSS rules for the element's class: dense
 * must emit an `@media (min-width:0px)` rule carrying the compact `xs` value,
 * and default must emit no such override at all.
 */
function renderCard(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

/** All emitted CSS rule text (base + media) referencing the element's Emotion class. */
function cssRulesFor(el: HTMLElement): string {
  const cls = Array.from(el.classList).find((c) => c.startsWith('css-'));
  if (!cls) return '';
  const styleText = Array.from(document.querySelectorAll('style'))
    .map((s) => s.textContent ?? '')
    .join('\n');
  const escaped = cls.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(
    `[^}@]*\\.${escaped}\\{[^}]*\\}|@media[^{]*\\{\\.${escaped}\\{[^}]*\\}\\}`,
    'g'
  );
  return (styleText.match(re) ?? []).join('\n');
}

describe('MetricCard', () => {
  it('renders the value and label text', () => {
    renderCard(<MetricCard value={42} label="Total Jobs" />);
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('Total Jobs')).toBeInTheDocument();
  });

  describe('default (no dense prop)', () => {
    it('renders the value WITHOUT the compact metricValue override', () => {
      renderCard(<MetricCard value={7} label="Default" />);

      const value = screen.getByText('7');
      // Theme h3 base size is reported by getComputedStyle...
      expect(value).toHaveStyle({ fontSize: theme.typography.h3.fontSize as string });
      // ...and crucially the compact xs override is never emitted (no media rule).
      expect(cssRulesFor(value)).not.toContain(RESPONSIVE.fontSize.metricValue.xs);
    });

    it('renders the label WITHOUT the compact metricLabel override', () => {
      renderCard(<MetricCard value={7} label="Default Label" />);

      const label = screen.getByText('Default Label');
      expect(cssRulesFor(label)).not.toContain(RESPONSIVE.fontSize.metricLabel.xs);
    });
  });

  describe('dense', () => {
    it('renders the value WITH the compact RESPONSIVE.fontSize.metricValue override', () => {
      renderCard(<MetricCard value={7} label="Dense" dense />);

      const value = screen.getByText('7');
      const rules = cssRulesFor(value);
      // The compact xs slot is emitted as a media rule on the element's class.
      expect(rules).toContain(RESPONSIVE.fontSize.metricValue.xs);
      expect(rules).toContain('@media');
    });

    it('renders the label WITH the compact RESPONSIVE.fontSize.metricLabel override', () => {
      renderCard(<MetricCard value={7} label="Dense Label" dense />);

      const label = screen.getByText('Dense Label');
      const rules = cssRulesFor(label);
      expect(rules).toContain(RESPONSIVE.fontSize.metricLabel.xs);
      expect(rules).toContain('@media');
    });
  });

  it('emits a different value font-size rule set for dense vs default', () => {
    const { unmount } = renderCard(<MetricCard value={1} label="A" />);
    const defaultRules = cssRulesFor(screen.getByText('1'));
    unmount();

    renderCard(<MetricCard value={1} label="A" dense />);
    const denseRules = cssRulesFor(screen.getByText('1'));

    expect(denseRules).not.toBe(defaultRules);
    expect(defaultRules).not.toContain(RESPONSIVE.fontSize.metricValue.xs);
    expect(denseRules).toContain(RESPONSIVE.fontSize.metricValue.xs);
  });
});
