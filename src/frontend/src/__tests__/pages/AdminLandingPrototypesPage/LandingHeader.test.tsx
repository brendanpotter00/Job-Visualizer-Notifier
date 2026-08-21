import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { LandingHeader } from '../../../pages/AdminLandingPrototypesPage/sections/LandingHeader';
import { LANDING_CONTENT } from '../../../pages/AdminLandingPrototypesPage/content';

const { header } = LANDING_CONTENT;

function renderHeader() {
  return renderWithProviders(<LandingHeader content={LANDING_CONTENT} />, {
    initialEntries: ['/admin/landing-prototypes'],
  });
}

/** Buttons only — the nav/footer carry plain text links in the same bar. */
function buttonLink(name: string) {
  const matches = screen
    .getAllByRole('link', { name })
    .filter((el) => el.classList.contains('MuiButton-root'));
  expect(matches, `expected exactly one button link named ${name}`).toHaveLength(1);
  return matches[0];
}

describe('LandingHeader', () => {
  it('renders the wordmark as a plain-text link home', () => {
    renderHeader();
    const mark = screen.getByRole('link', { name: header.wordmark.label });
    expect(mark).toHaveAttribute('href', header.wordmark.to);
    expect(mark).not.toHaveClass('MuiButton-root');
    expect(mark).toHaveTextContent('onesecondswe');
  });

  it('renders exactly the two quiet nav links from content, with their route targets', () => {
    renderHeader();
    const nav = screen.getByRole('navigation', { name: 'Landing' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((el) => el.textContent)).toEqual(header.nav.map((item) => item.label));
    for (const item of header.nav) {
      expect(within(nav).getByRole('link', { name: item.label })).toHaveAttribute('href', item.to);
    }
  });

  it('pairs a text "Log in" with a contained "Sign up", both on the mock account route', () => {
    renderHeader();
    const logIn = buttonLink(header.logIn.label);
    expect(logIn).toHaveClass('MuiButton-text');
    expect(logIn).toHaveAttribute('href', header.logIn.to);

    const signUp = buttonLink(header.signUp.label);
    expect(signUp).toHaveClass('MuiButton-contained');
    expect(signUp).toHaveAttribute('href', header.signUp.to);
  });

  it('exposes the source-code mark as a labelled, safely-targeted external link', () => {
    renderHeader();
    const source = screen.getByRole('link', { name: header.sourceCode.label });
    expect(source).toHaveAttribute('href', header.sourceCode.href);
    expect(source).toHaveAttribute('target', '_blank');
    expect(source).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(source).toHaveAttribute('aria-label', 'Source code');
  });

  it('starts transparent over the hero, with the scroll sentinel above the bar', () => {
    renderHeader();
    const bar = screen.getByTestId('landing-header');
    // No scroll has happened, so the observer never fires: the bar is still in
    // its over-the-hero state.
    expect(bar).toHaveAttribute('data-scrolled', 'false');
    const sentinel = screen.getByTestId('landing-header-sentinel');
    expect(
      sentinel.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING,
      'the sentinel must precede the bar or it can never report the top of the page'
    ).toBeTruthy();
  });
});
