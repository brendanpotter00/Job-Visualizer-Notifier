import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { LandingPage } from '../../../pages/LandingPage/LandingPage';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import type { LandingPrototypeProps } from '../../../pages/LandingPage/types';

// Mock at the lazy boundary: vi.mock intercepts the dynamic import() inside
// React.lazy, so the shell's own contract (fixture toggle, prop plumbing, the
// Suspense boundary, the document head) is exercised without mounting the
// scene — which would drag three/rapier into the test process and defeat the
// point of the boundary.
vi.mock('../../../pages/LandingPage/prototypes/GravityPrototype/GravityPrototype', () => ({
  default: (props: LandingPrototypeProps) => (
    <div data-testid="landing-body">
      gravity ({props.sparse ? 'sparse' : 'rich'}, {props.jobs.length} jobs, now={props.now})
    </div>
  ),
}));

function renderPage(url = '/landing') {
  return renderWithProviders(<LandingPage />, { initialEntries: [url] });
}

describe('LandingPage', () => {
  it('renders the Gravity landing body behind a Suspense boundary', async () => {
    renderPage();
    expect(await screen.findByTestId('landing-body')).toHaveTextContent(/gravity \(rich/);
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

  it('?data=sparse swaps in the sparse fixture', async () => {
    renderPage('/landing?data=sparse');
    expect(await screen.findByTestId('landing-body')).toHaveTextContent(/gravity \(sparse/);
  });

  it('any other ?data= value keeps the rich fixture', async () => {
    renderPage('/landing?data=nonsense');
    expect(await screen.findByTestId('landing-body')).toHaveTextContent(/gravity \(rich/);
  });

  // Fixtures and "now" are threaded from the shell so nothing below it samples
  // Date.now() during render (react-hooks/purity) and so the two fixtures stay
  // genuinely different sets rather than the same list twice.
  it('hands the body a non-empty fixture and the shared render clock', async () => {
    renderPage();
    const body = await screen.findByTestId('landing-body');
    const jobs = Number(/(\d+) jobs/.exec(body.textContent ?? '')?.[1]);
    const now = Number(/now=(\d+)/.exec(body.textContent ?? '')?.[1]);
    expect(jobs).toBeGreaterThan(0);
    expect(now).toBeGreaterThan(0);
  });

  // The head is the shell's job, not the scene's: the title and description
  // are applied the moment the route mounts, before (and regardless of
  // whether) the lazy scene chunk arrives, and the canonical is hoisted.
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

  // The title and description are edited IN PLACE on the static head (a
  // rendered <title> would sit behind index.html's and never win), so leaving
  // the route must hand the app back exactly what it had — otherwise every
  // page after /landing would carry the landing title.
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
