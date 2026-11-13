import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';

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
