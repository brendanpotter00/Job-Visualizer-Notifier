import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';

/**
 * The static head in index.html is the site-wide default, the link-preview
 * card, and the whole page for any crawler that never runs JavaScript. It has
 * no runtime test surface, so its SEO shape is pinned here from the file.
 * (`__dirname`, not `import.meta.url`: under the jsdom environment the latter
 * is an http://localhost URL, which `readFileSync` refuses.)
 */
const html = readFileSync(resolve(__dirname, '../../../../index.html'), 'utf8');

function tag(pattern: RegExp): string {
  const match = pattern.exec(html);
  expect(match, `index.html is missing ${pattern}`).not.toBeNull();
  return match![1];
}

describe('index.html static head', () => {
  it('carries exactly one brand-first title with the query phrase', () => {
    expect(html.match(/<title>/g)).toHaveLength(1);
    const title = tag(/<title>([^<]+)<\/title>/);
    expect(title).toMatch(/^onesecondswe/);
    expect(title).toMatch(/software engineer jobs/i);
    expect(title.length).toBeLessThanOrEqual(70);
  });

  // `/landing` overrides the title and description at runtime, and the sitemap
  // submits both `/` and `/landing`: two URLs sharing one title and description
  // is the duplicate-content signal this head must not send.
  it('does not share its title or description with the landing page', () => {
    const title = tag(/<title>([^<]+)<\/title>/);
    const description = tag(/<meta\s+name="description"\s+content="([^"]+)"/);
    expect(title).not.toBe(LANDING_CONTENT.seo.title);
    expect(description).not.toBe(LANDING_CONTENT.seo.description);
  });

  it('carries a short, answer-first description', () => {
    const description = tag(/<meta\s+name="description"\s+content="([^"]+)"/);
    expect(description.length).toBeLessThanOrEqual(160);
    expect(description).toMatch(/software engineer jobs/i);
  });

  // Link-preview scrapers never run JS and resolve nothing relative, so the
  // card image must be absolute on the production origin.
  it('points the social card at an absolute production image', () => {
    const ogImage = tag(/<meta\s+property="og:image"\s+content="([^"]+)"/);
    const twitterImage = tag(/<meta\s+name="twitter:image"\s+content="([^"]+)"/);
    expect(ogImage).toBe(`${LANDING_CONTENT.seo.siteUrl}${LANDING_CONTENT.seo.ogImagePath}`);
    expect(twitterImage).toBe(ogImage);
    expect(tag(/<meta\s+property="og:title"\s+content="([^"]+)"/)).toBe(
      tag(/<title>([^<]+)<\/title>/)
    );
  });
});
