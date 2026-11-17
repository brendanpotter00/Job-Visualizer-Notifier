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
  it('carries exactly one title, the same one the landing page sets', () => {
    expect(html.match(/<title>/g)).toHaveLength(1);
    expect(tag(/<title>([^<]+)<\/title>/)).toBe(LANDING_CONTENT.seo.title);
  });

  it('carries the landing page description', () => {
    expect(tag(/<meta\s+name="description"\s+content="([^"]+)"/)).toBe(
      LANDING_CONTENT.seo.description
    );
  });

  it('points the social card at an absolute production image', () => {
    const ogImage = tag(/<meta\s+property="og:image"\s+content="([^"]+)"/);
    const twitterImage = tag(/<meta\s+name="twitter:image"\s+content="([^"]+)"/);
    expect(ogImage).toBe(`${LANDING_CONTENT.seo.siteUrl}${LANDING_CONTENT.seo.ogImagePath}`);
    expect(twitterImage).toBe(ogImage);
    expect(tag(/<meta\s+property="og:title"\s+content="([^"]+)"/)).toBe(LANDING_CONTENT.seo.title);
    expect(tag(/<meta\s+name="twitter:title"\s+content="([^"]+)"/)).toBe(LANDING_CONTENT.seo.title);
    expect(tag(/<meta\s+property="og:description"\s+content="([^"]+)"/)).toBe(
      LANDING_CONTENT.seo.description
    );
    expect(tag(/<meta\s+name="twitter:description"\s+content="([^"]+)"/)).toBe(
      LANDING_CONTENT.seo.description
    );
  });
});
