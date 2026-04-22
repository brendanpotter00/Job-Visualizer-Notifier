import { describe, it, expect } from 'vitest';
import { ROUTES, NAV_ITEMS } from '../../config/routes';

describe('routes config', () => {
  describe('ROUTES', () => {
    it('exposes the VOTE_FEATURES path at /vote-features', () => {
      expect(ROUTES.VOTE_FEATURES).toBe('/vote-features');
    });

    it('keeps existing routes stable', () => {
      expect(ROUTES.RECENT_JOBS).toBe('/');
      expect(ROUTES.COMPANIES).toBe('/companies');
      expect(ROUTES.WHY).toBe('/why');
      expect(ROUTES.QA).toBe('/qa');
      expect(ROUTES.ACCOUNT).toBe('/account');
    });

    it('contains no duplicate paths', () => {
      const paths = Object.values(ROUTES);
      expect(new Set(paths).size).toBe(paths.length);
    });
  });

  describe('NAV_ITEMS', () => {
    it('includes a "Vote for features" item wired to ROUTES.VOTE_FEATURES with the ThumbUp icon', () => {
      const voteItem = NAV_ITEMS.find((item) => item.path === ROUTES.VOTE_FEATURES);
      expect(voteItem).toBeDefined();
      expect(voteItem?.label).toBe('Vote for features');
      expect(voteItem?.icon).toBe('ThumbUp');
    });

    it('every NAV_ITEMS path matches a ROUTES value', () => {
      const routeValues = new Set<string>(Object.values(ROUTES));
      for (const item of NAV_ITEMS) {
        expect(routeValues.has(item.path)).toBe(true);
      }
    });

    it('NAV_ITEMS paths are unique', () => {
      const paths = NAV_ITEMS.map((item) => item.path);
      expect(new Set(paths).size).toBe(paths.length);
    });
  });
});
