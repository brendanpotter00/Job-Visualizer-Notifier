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

  // The head is the shell's job, not the scene's: React 19 hoists the title,
  // description and canonical into <head> the moment the route mounts, so they
  // exist before (and regardless of whether) the lazy scene chunk arrives.
  it('puts the SEO head on the page: title, description, canonical, social card', async () => {
    renderPage();
    await screen.findByTestId('landing-body');
    const { seo } = LANDING_CONTENT;
    const canonical = `${seo.siteUrl}${seo.canonicalPath}`;
    expect(document.title).toBe(seo.title);
    expect(document.querySelector('meta[name="description"]')).toHaveAttribute(
      'content',
      seo.description
    );
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute('href', canonical);
    expect(document.querySelector('meta[property="og:url"]')).toHaveAttribute('content', canonical);
    expect(document.querySelector('meta[property="og:image"]')).toHaveAttribute(
      'content',
      `${seo.siteUrl}${seo.ogImagePath}`
    );
    expect(document.querySelector('meta[name="twitter:card"]')).toHaveAttribute(
      'content',
      'summary_large_image'
    );
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
