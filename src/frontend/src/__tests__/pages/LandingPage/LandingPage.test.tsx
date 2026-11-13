import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { LandingPage } from '../../../pages/LandingPage/LandingPage';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import type { LandingPrototypeProps } from '../../../pages/LandingPage/types';

vi.mock('../../../pages/LandingPage/prototypes/GravityPrototype/GravityPrototype', () => {
  const GravityPrototype = (props: LandingPrototypeProps) => (
    <div data-testid="landing-body" data-prop-keys={Object.keys(props).join(',')}>
      gravity ({props.content.productName})
    </div>
  );
  return { GravityPrototype };
});

function renderPage(url = '/') {
  return renderWithProviders(<LandingPage />, { initialEntries: [url] });
}

describe('LandingPage', () => {
  it('renders the Gravity landing body', async () => {
    renderPage();
    expect(await screen.findByTestId('landing-body')).toHaveTextContent(
      `gravity (${LANDING_CONTENT.productName})`
    );
  });

  // The four-tab workspace is gone (2026-09-03 consolidation). There is exactly
  // one design now, so any tab chrome coming back is a regression, not a
  // feature — assert its absence rather than trusting the deletion to stick.
  it('renders no prototype tab chrome', async () => {
    renderPage();
    await screen.findByTestId('landing-body');
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
  });

  it.each(['/', '/?data=sparse'])('hands the body only its content at %s', async (url) => {
    renderPage(url);
    expect(await screen.findByTestId('landing-body')).toHaveAttribute('data-prop-keys', 'content');
  });

  it('puts the SEO head on the page: title, description, canonical', async () => {
    renderPage();
    await screen.findByTestId('landing-body');
    const { seo } = LANDING_CONTENT;
    expect(document.title).toBe(seo.title);
    expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(document.head.querySelector('meta[name="description"]')).toHaveAttribute(
      'content',
      seo.description
    );
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute(
      'href',
      `${seo.siteUrl}${seo.canonicalPath}`
    );
  });

  it('overrides the static title and description in place, and restores them on unmount', async () => {
    const staticTitle = 'app default title';
    const staticDescription = 'app default description';
    document.title = staticTitle;
    const meta = document.createElement('meta');
    meta.name = 'description';
    meta.content = staticDescription;
    document.head.appendChild(meta);
    try {
      const { unmount } = renderPage();
      await screen.findByTestId('landing-body');
      expect(document.title).toBe(LANDING_CONTENT.seo.title);
      expect(meta).toHaveAttribute('content', LANDING_CONTENT.seo.description);
      expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1);

      unmount();
      expect(document.title).toBe(staticTitle);
      expect(meta).toHaveAttribute('content', staticDescription);
    } finally {
      meta.remove();
      document.title = '';
    }
  });

  it('embeds the JSON-LD graph with one FAQ question per content entry', async () => {
    renderPage();
    await screen.findByTestId('landing-body');
    const script = screen.getByTestId('landing-json-ld');
    expect(script).toHaveAttribute('type', 'application/ld+json');
    const graph = JSON.parse(script.textContent ?? '') as {
      '@graph': { '@type': string; mainEntity?: unknown[] }[];
    };
    const faq = graph['@graph'].find((node) => node['@type'] === 'FAQPage');
    expect(faq?.mainEntity).toHaveLength(LANDING_CONTENT.faq.entries.length);
  });
});
